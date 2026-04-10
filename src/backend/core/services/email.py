"""Email notification service for transfer events."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def notify_owner_link_opened(transfer):
    """Notify the transfer owner that the download link was opened."""
    if not transfer.owner or not transfer.owner.email:
        return

    file = transfer.files.first()
    filename = file.filename if file else "—"

    subject = f"Votre transfert « {transfer.title or filename} » a été consulté"
    body = render_to_string(
        "core/emails/link_opened.txt",
        {"transfer": transfer, "filename": filename},
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[transfer.owner.email],
    )
    logger.info("Sent link_opened notification for transfer %s", transfer.id)


def notify_owner_file_downloaded(transfer, filename):
    """Notify the transfer owner that a file was downloaded."""
    if not transfer.owner or not transfer.owner.email:
        return

    subject = f"Votre fichier « {filename} » a été téléchargé"
    body = render_to_string(
        "core/emails/file_downloaded.txt",
        {"transfer": transfer, "filename": filename},
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[transfer.owner.email],
    )
    logger.info("Sent file_downloaded notification for transfer %s", transfer.id)
