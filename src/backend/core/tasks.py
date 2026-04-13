"""Celery tasks for the transferts core app."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from celery import shared_task

from core.enums import ActorType, TransferEventType, TransferStatus
from core.models import Transfer, TransferEvent, TransferFile
from core.services import s3 as s3_service

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
        for tf in transfer.files.all():
            try:
                s3_service.delete_object(tf.s3_key)
            except Exception:
                logger.exception(
                    "Failed to delete S3 object %s for transfer %s",
                    tf.s3_key,
                    transfer.id,
                )

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
    """Clean up transfers whose multipart upload never completed.

    A transfer is "abandoned" if its only ``TransferFile`` still has an
    ``upload_id`` set (no ``upload_completed_at``) more than 24 hours after
    creation. This happens when the user closes their tab mid-upload or when
    the browser crashes. We abort the S3 multipart upload to free S3-side
    state, then delete the DB rows.
    """
    cutoff = timezone.now() - timedelta(hours=24)
    orphan_files = TransferFile.objects.filter(
        upload_completed_at__isnull=True,
        created_at__lte=cutoff,
    ).select_related("transfer")

    count = 0
    for tf in orphan_files:
        if tf.upload_id:
            try:
                s3_service.abort_multipart_upload(tf.s3_key, tf.upload_id)
            except Exception:
                logger.exception(
                    "Failed to abort multipart upload %s for %s",
                    tf.upload_id,
                    tf.s3_key,
                )
        transfer = tf.transfer
        tf.delete()
        if not TransferFile.objects.filter(transfer=transfer).exists():
            transfer.delete()
        count += 1

    if count:
        logger.info("Cleaned up %d abandoned upload(s).", count)


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

    from core.services.email import notify_owner_link_opened

    notify_owner_link_opened(transfer)


@shared_task
def send_file_downloaded_notification(transfer_id, filename):
    """Notify the owner that a file was downloaded."""
    try:
        transfer = Transfer.objects.select_related("owner").get(id=transfer_id)
    except Transfer.DoesNotExist:
        return

    from core.services.email import notify_owner_file_downloaded

    notify_owner_file_downloaded(transfer, filename)
