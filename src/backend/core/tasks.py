"""Celery tasks for the transferts core app."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from celery import shared_task

from core.enums import ActorType, TransferEventType, TransferStatus
from core.models import Transfer, TransferEvent
from core.services.email import (
    notify_owner_file_downloaded,
    notify_owner_link_opened,
    send_recipient_invitation,
)

logger = logging.getLogger(__name__)


@shared_task
def record_expired_transfers_task():
    """Record (mark + audit) transfers whose expiry date has passed.

    Public access is already gated by ``Transfer.is_accessible`` (which checks
    ``expires_at <= now``), so this task does NOT actually cause expiration.
    It only flips ``status: ACTIVE → EXPIRED`` for filtering/listing purposes
    and emits an audit ``TRANSFER_EXPIRED`` event.

    Files are NOT deleted here — they remain in S3 during the grace period
    so the transfer can be reactivated. Actual file deletion is handled by
    ``delete_expired_transfer_files_task``.
    """
    now = timezone.now()
    transfers_to_expire = Transfer.objects.filter(
        status=TransferStatus.ACTIVE,
        expires_at__lte=now,
    )

    count = 0
    for transfer in transfers_to_expire:
        transfer.status = TransferStatus.EXPIRED
        transfer.save(update_fields=["status", "updated_at"])

        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_EXPIRED,
            actor_type=ActorType.AGENT,
        )
        count += 1

    if count:
        logger.info("Expired %d transfer(s).", count)


@shared_task
def delete_expired_transfer_files_task():
    """Delete S3 files for transfers that expired more than the grace period ago.

    Once files are deleted, ``files_deleted_at`` is set and the transfer
    can no longer be reactivated.
    """
    grace_days = settings.TRANSFER_FILE_GRACE_PERIOD_DAYS
    cutoff = timezone.now() - timedelta(days=grace_days)

    transfers = Transfer.objects.filter(
        status=TransferStatus.EXPIRED,
        files_deleted_at__isnull=True,
        expires_at__lte=cutoff,
    ).prefetch_related("files")

    if not transfers.exists():
        return

    count = 0

    for transfer in transfers:
        transfer.delete_s3_objects()

        transfer.files_deleted_at = timezone.now()
        transfer.save(update_fields=["files_deleted_at", "updated_at"])

        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.FILES_DELETED,
            actor_type=ActorType.AGENT,
        )
        count += 1

    logger.info("Deleted files for %d expired transfer(s).", count)


@shared_task
def cleanup_abandoned_uploads_task():
    """Clean up transfers whose upload was never finalized.

    A transfer is "abandoned" if its ``upload_completed_at`` is still null
    more than 24 hours after creation. This happens when the user closes
    their tab mid-upload, the browser crashes, or they never call
    ``finalize``. All-or-nothing semantics: even if some of the files were
    individually completed, the whole transfer is nuked (S3 multipart
    uploads aborted, DB rows deleted).
    """
    cutoff = timezone.now() - timedelta(hours=24)
    abandoned = Transfer.objects.filter(
        upload_completed_at__isnull=True,
        created_at__lte=cutoff,
    ).prefetch_related("files")

    count = 0
    for transfer in abandoned:
        transfer.abort_pending_uploads()
        transfer.delete()
        count += 1

    if count:
        logger.info("Cleaned up %d abandoned transfer(s).", count)


@shared_task
def send_recipient_invitations_task(transfer_id):
    """Send invitation emails to all recipients of an email-mode transfer."""
    try:
        transfer = (
            Transfer.objects.select_related("owner")
            .get(id=transfer_id)
        )
    except Transfer.DoesNotExist:
        return

    for recipient in transfer.recipients.filter(email_sent_at__isnull=True):
        try:
            send_recipient_invitation(transfer, recipient)
            recipient.email_sent_at = timezone.now()
            recipient.save(update_fields=["email_sent_at", "updated_at"])
            TransferEvent.objects.create(
                transfer_id=transfer.id,
                recipient_id=recipient.id,
                event_type=TransferEventType.EMAIL_SENT,
                actor_type=ActorType.AGENT,
                actor_id=transfer.owner_id,
                payload={"email": recipient.email},
            )
        except Exception:
            logger.exception(
                "Failed to send invitation to %s for transfer %s",
                recipient.email,
                transfer_id,
            )


@shared_task
def send_link_opened_notification(transfer_id):
    """Notify the owner that their transfer link was opened."""
    try:
        transfer = (
            Transfer.objects.select_related("owner")
            .prefetch_related("files")
            .get(id=transfer_id)
        )
    except Transfer.DoesNotExist:
        return
    notify_owner_link_opened(transfer)


@shared_task
def send_file_downloaded_notification(transfer_id, filename):
    """Notify the owner that a file was downloaded."""
    try:
        transfer = Transfer.objects.select_related("owner").get(id=transfer_id)
    except Transfer.DoesNotExist:
        return
    notify_owner_file_downloaded(transfer, filename)
