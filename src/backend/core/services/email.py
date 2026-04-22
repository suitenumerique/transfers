"""Email notification service for transfer events."""

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


def _common_context(base_url: str) -> dict:
    """Brand chrome shared by every email template — Transferts wordmark
    in the header, République Française + La Suite territoriale logos in
    the footer. Identical between recipient and owner mails so the
    visual identity stays consistent."""
    return {
        "logo_url": f"{base_url}/images/transferts-logo.svg",
        "rf_logo_url": f"{base_url}/images/republique-francaise.svg",
        "st_logo_url": f"{base_url}/images/lasuite-territoriale.svg",
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


def _owner_summary_url(transfer) -> str:
    """Absolute URL of the agent-side transfer detail (recap) page."""
    return f"{_public_base_url()}/transfers/{transfer.id}"


def notify_owner_link_opened(transfer):
    """Notify the transfer owner that the download link was opened."""
    if not getattr(settings, "NOTIFY_SENDER_EVENTS", False):
        return
    if not transfer.owner or not transfer.owner.email:
        return

    file = transfer.files.first()
    filename = file.filename if file else "—"

    base_url = _public_base_url()
    subject = f"Votre transfert « {transfer.title or filename} » a été consulté"
    ctx = {
        **_common_context(base_url),
        "subject": subject,
        "transfer": transfer,
        "filename": filename,
        "banner_label": "Votre transfert a été consulté.",
        "banner_icon": "&#128065;",  # eye
        "cta_url": _owner_summary_url(transfer),
        "cta_label": "Voir le récapitulatif",
        "cta_icon": "&#8505;",  # info
    }

    _send_multipart(
        subject=subject,
        text_body=render_to_string("core/emails/link_opened.txt", ctx),
        html_body=render_to_string("core/emails/link_opened.html", ctx),
        to=[transfer.owner.email],
    )
    logger.info("Sent link_opened notification for transfer %s", transfer.id)


def notify_owner_file_downloaded(transfer, filename):
    """Notify the transfer owner that a file was downloaded."""
    if not getattr(settings, "NOTIFY_SENDER_EVENTS", False):
        return
    if not transfer.owner or not transfer.owner.email:
        return

    base_url = _public_base_url()
    subject = f"Votre fichier « {filename} » a été téléchargé"
    ctx = {
        **_common_context(base_url),
        "subject": subject,
        "transfer": transfer,
        "filename": filename,
        "banner_label": "Un fichier a été téléchargé.",
        "banner_icon": "&#x2B07;",  # down arrow
        "cta_url": _owner_summary_url(transfer),
        "cta_label": "Voir le récapitulatif",
        "cta_icon": "&#8505;",  # info
    }

    _send_multipart(
        subject=subject,
        text_body=render_to_string("core/emails/file_downloaded.txt", ctx),
        html_body=render_to_string("core/emails/file_downloaded.html", ctx),
        to=[transfer.owner.email],
    )
    logger.info("Sent file_downloaded notification for transfer %s", transfer.id)
