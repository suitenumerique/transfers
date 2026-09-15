"""Email notification service for transfer events."""

import json
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import formats, timezone

from core.services.recipient_activity import activity_for

logger = logging.getLogger(__name__)


def _public_base_url() -> str:
    """Base URL of the deployed frontend (used to build absolute links in
    emails). Falls back to LOGIN_REDIRECT_URL — that's the post-login
    redirect target and points at the same hostname in every env."""
    base = getattr(settings, "PUBLIC_BASE_URL", None) or getattr(
        settings, "LOGIN_REDIRECT_URL", ""
    )
    return (base or "").rstrip("/")


def _footer_logos() -> list[dict]:
    """Parse ``EMAIL_FOOTER_LOGOS`` (JSON list of ``{url, alt, width,
    height}``) into the entries the footer loops over. Entries without a
    ``url`` are dropped; a malformed value logs and yields no logo rather
    than failing every notification — a branding typo must not block
    delivery."""
    raw = getattr(settings, "EMAIL_FOOTER_LOGOS", "") or "[]"
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("EMAIL_FOOTER_LOGOS is not valid JSON; rendering no footer logo")
        return []
    if not isinstance(parsed, list):
        logger.warning(
            "EMAIL_FOOTER_LOGOS must be a JSON list; rendering no footer logo"
        )
        return []
    logos = []
    for index, entry in enumerate(parsed):
        # ``url`` must be a non-blank string: a number or whitespace would
        # otherwise land verbatim in ``src="…"`` as a broken image. Dropped
        # entries are logged like the malformed-JSON case above — the
        # operator sees a logo missing and needs a trace to know why. The
        # index is enough to find it; no need to dump the entry itself.
        url = entry.get("url") if isinstance(entry, dict) else None
        url = url.strip() if isinstance(url, str) else ""
        if not url:
            logger.warning(
                "EMAIL_FOOTER_LOGOS entry %d dropped: missing or blank url", index
            )
            continue
        logos.append(
            {
                "url": url,
                "alt": entry.get("alt", ""),
                "width": entry.get("width"),
                "height": entry.get("height"),
            }
        )
    return logos


def _common_context(base_url: str) -> dict:
    """Brand chrome shared by every email template. Nothing institutional
    is hardcoded: the header logo and the footer logos come from settings
    (see ``EMAIL_LOGO_IMG`` / ``EMAIL_FOOTER_LOGOS``), so a self-hosted
    instance never ships state marks it isn't allowed to use. The only
    baked-in default is the product's own wordmark for the header.

    PNG, not SVG, for anything you point these at: Gmail, Outlook (desktop
    and web), Yahoo and iOS Mail do not render ``<img src="…svg">``.
    """
    custom_logo = (getattr(settings, "EMAIL_LOGO_IMG", "") or "").strip()
    return {
        # The shipped wordmark is a 2x raster (476x80) sized for the 238x40
        # box in _base.html. A custom logo has an unknown ratio, so the
        # template renders it at 40px high with its natural width.
        "logo_url": custom_logo or f"{base_url}/images/transferts-logo.png",
        "logo_width": None if custom_logo else 238,
        "footer_logos": _footer_logos(),
        "terms_url": getattr(settings, "TERMS_URL", ""),
    }


def _send_multipart(*, subject, text_body, html_body, to, connection=None):
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        # ``None`` makes Django open (and close) a fresh SMTP session for
        # this one message; a batch sender passes a shared connection.
        connection=connection,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()


def send_recipient_invitation(transfer, recipient, connection=None):
    """Send a download link email to a single recipient.

    ``connection`` is an already-open mail connection to reuse; the batch
    task passes one so a 50-recipient transfer costs one SMTP handshake
    (TCP + TLS + AUTH) instead of fifty.

    Multipart message — HTML body matching the design mock plus a
    plain-text fallback for clients that strip HTML or filter on text.

    The email carries only the download link, never the decryption key.
    A non-confidential transfer's key is served by the backend at
    download time; a confidential transfer's key never reaches us (the
    sender delivers it out of band). So no fragment or key is ever
    appended to the URL here.
    """
    base_url = _public_base_url()
    sender_name = (
        (transfer.owner.full_name or transfer.owner.email)
        if transfer.owner
        else "Un agent"
    )
    sender_email = transfer.owner.email if transfer.owner else ""
    # ``?r=<token>`` is what lets the download page attribute this
    # recipient's opens and downloads (every recipient shares the same
    # public token). It grants nothing beyond what the link already does.
    download_url = f"{base_url}/t/{transfer.public_token}?r={recipient.token}"
    files = list(transfer.files.all())
    total_size = sum(f.size for f in files)
    expires_at = timezone.localtime(transfer.expires_at)

    subject = f"{sender_name} vous a envoyé des fichiers"
    ctx = {
        **_common_context(base_url),
        "subject": subject,
        "transfer": transfer,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "files": files,
        "total_size": total_size,
        "expires_date": formats.date_format(expires_at, "d/m/Y"),
        "expires_time": expires_at.strftime("%Hh%M"),
        "banner_label": "Nouveau transfert partagé avec vous.",
        "banner_icon": "&#x21C5;",
        "verb_label": "vous a transféré",
        "cta_url": download_url,
        "cta_label": "Télécharger les fichiers",
        "cta_icon": "&#x2B07;",
        "download_url": download_url,
    }

    _send_multipart(
        subject=subject,
        text_body=render_to_string("core/emails/recipient_invitation.txt", ctx),
        html_body=render_to_string("core/emails/recipient_invitation.html", ctx),
        to=[recipient.email],
        connection=connection,
    )
    logger.info(
        "Sent invitation to recipient %s for transfer %s", recipient.id, transfer.id
    )


def send_download_receipt(transfer, recipient, connection=None):
    """Tell the sender what ``recipient`` has downloaded. Sent once per
    recipient (the task stamps ``download_notified_at`` before calling
    this) and only when the sender opted in (``notify_on_download``).
    Reports the state at send time: every file, or "n of N" for a
    recipient who stopped partway (the delayed trigger)."""
    owner = transfer.owner
    if owner is None or not owner.email:
        return
    base_url = _public_base_url()
    files = list(transfer.files.all())
    total_size = sum(f.plaintext_size or f.size for f in files)
    activity = activity_for(transfer.id, recipient.id)
    for f in files:
        f.downloaded = str(f.id) in activity.downloaded_file_ids
    downloaded_count = sum(1 for f in files if f.downloaded)
    complete = downloaded_count >= len(files)
    downloaded_at = timezone.localtime(activity.downloaded_at or timezone.now())
    detail_url = f"{base_url}/transfers/{transfer.id}"

    if complete:
        subject = f"{recipient.email} a téléchargé vos fichiers"
    else:
        noun = "fichier" if downloaded_count == 1 else "fichiers"
        subject = (
            f"{recipient.email} a téléchargé {downloaded_count} {noun} sur {len(files)}"
        )
    ctx = {
        **_common_context(base_url),
        "subject": subject,
        "transfer": transfer,
        "recipient_email": recipient.email,
        "files": files,
        "total_size": total_size,
        "complete": complete,
        "downloaded_count": downloaded_count,
        "total_count": len(files),
        "downloaded_date": formats.date_format(downloaded_at, "d/m/Y"),
        "downloaded_time": downloaded_at.strftime("%Hh%M"),
        "banner_label": "Vos fichiers ont été téléchargés.",
        "banner_icon": "&#x2B07;",
        "cta_url": detail_url,
        "cta_label": "Voir le transfert",
        "cta_icon": "&#x2197;",
        "detail_url": detail_url,
    }

    _send_multipart(
        subject=subject,
        text_body=render_to_string("core/emails/download_receipt.txt", ctx),
        html_body=render_to_string("core/emails/download_receipt.html", ctx),
        to=[owner.email],
        connection=connection,
    )
    logger.info(
        "Sent download receipt to owner %s for transfer %s (recipient %s)",
        owner.id,
        transfer.id,
        recipient.id,
    )
