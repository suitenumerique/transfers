"""Celery tasks for the transferts core app."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

import boto3
from celery import shared_task

from core.enums import ActorType, TransferEventType, TransferStatus
from core.models import Transfer, TransferEvent

logger = logging.getLogger(__name__)


def _get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", None) or "us-east-1",
    )


@shared_task
def expire_transfers_task():
    """Mark active transfers past their expiry date as expired.

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

    s3 = _get_s3_client()
    bucket = settings.TRANSFERS_BUCKET_NAME
    count = 0

    for transfer in transfers:
        for tf in transfer.files.all():
            try:
                s3.delete_object(Bucket=bucket, Key=tf.s3_key)
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
def send_link_opened_notification(transfer_id):
    """Notify the owner that their transfer link was opened."""
    try:
        transfer = Transfer.objects.select_related("owner").prefetch_related("files").get(id=transfer_id)
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
