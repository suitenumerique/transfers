"""Email notification service for transfer events."""

import json
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import formats, timezone

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
    for entry in parsed:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        logos.append(
            {
                "url": entry["url"],
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


def _send_multipart(*, subject, text_body, html_body, to):
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()


def send_recipient_invitation(transfer, recipient):
    """Send a download link email to a single recipient.

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
    download_url = f"{base_url}/t/{transfer.public_token}"
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
    )
    logger.info("Sent invitation to %s for transfer %s", recipient.email, transfer.id)
