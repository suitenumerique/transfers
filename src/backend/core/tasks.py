"""Celery tasks for the transferts core app."""

import logging
from datetime import timedelta

from django.utils import timezone

from celery import shared_task

from core.enums import ActorType, TransferEventType, TransferStatus
from core.models import Transfer, TransferDraft, TransferEvent
from core.services import s3
from core.services.email import (
    notify_owner_file_downloaded,
    notify_owner_link_opened,
    send_recipient_invitation,
)

logger = logging.getLogger(__name__)


@shared_task
def expire_transfers_task():
    """Expire transfers whose expiry date has passed.

    Flips ``status: ACTIVE → EXPIRED``, deletes the underlying S3 files, and
    emits both ``TRANSFER_EXPIRED`` and ``FILES_DELETED`` audit events.
    Public access is already gated by ``Transfer.is_accessible`` so the
    deletion closes the loop atomically.
    """
    now = timezone.now()
    transfers_to_expire = Transfer.objects.filter(
        status=TransferStatus.ACTIVE,
        expires_at__lte=now,
    ).prefetch_related("files")

    count = 0
    for transfer in transfers_to_expire:
        transfer.delete_s3_objects()

        transfer.status = TransferStatus.EXPIRED
        transfer.save(update_fields=["status", "updated_at"])

        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_EXPIRED,
            actor_type=ActorType.AGENT,
        )
        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.FILES_DELETED,
            actor_type=ActorType.AGENT,
        )
        count += 1

    if count:
        logger.info("Expired %d transfer(s).", count)


@shared_task
def cleanup_abandoned_drafts_task():
    """Clean up drafts whose user never pressed "Create link".

    A draft is "abandoned" if it's still in ``TransferDraft`` more than 24
    hours after its creation — finalized transfers are never in this table.
    We best-effort abort every in-progress S3 multipart upload, delete every
    object already landed, then cascade-delete the draft (which takes its
    files with it).
    """
    cutoff = timezone.now() - timedelta(hours=24)
    abandoned = TransferDraft.objects.filter(
        created_at__lte=cutoff,
    ).prefetch_related("files")

    count = 0
    for draft in abandoned:
        for tf in draft.files.all():
            if tf.upload_id:
                s3.abort_multipart_upload(tf.s3_key, tf.upload_id)
            if tf.s3_key:
                s3.delete_object(tf.s3_key)
        draft.delete()
        count += 1

    if count:
        logger.info("Cleaned up %d abandoned draft(s).", count)


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
