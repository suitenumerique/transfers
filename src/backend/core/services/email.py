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


def send_recipient_invitation(transfer, recipient, *, key_fragment=""):
    """Send a download link email to a single recipient.

    Multipart message — HTML body matching the design mock plus a
    plain-text fallback for clients that strip HTML or filter on text.

    ``key_fragment``, when non-empty, is appended as the URL fragment so
    E2E recipients can decrypt. The fragment is not stored on the
    transfer; it's passed through from the finalize call via the email
    task's kwargs. Every relay between us and the recipient's mailbox
    sees the full link including the key — that is the price of mailing
    E2E links; for stricter sharing use link mode.
    """
    base_url = _public_base_url()
    sender_name = (
        (transfer.owner.full_name or transfer.owner.email)
        if transfer.owner
        else "Un agent"
    )
    sender_email = transfer.owner.email if transfer.owner else ""
    download_url = f"{base_url}/t/{transfer.public_token}"
    if key_fragment:
        download_url = f"{download_url}#{key_fragment}"
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
