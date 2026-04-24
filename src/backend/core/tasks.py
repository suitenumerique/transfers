"""Celery tasks for the transferts core app."""

import logging
from datetime import timedelta

from django.utils import timezone

import botocore
import requests
from celery import shared_task

from core.enums import (
    ActorType,
    DeactivationReason,
    TransferEventType,
    TransferStatus,
)
from core.models import Transfer, TransferDraft, TransferEvent, TransferFile
from core.services import s3
from core.services.email import send_recipient_invitation

logger = logging.getLogger(__name__)

# Chunk size used when streaming from a remote source (Drive) into S3's
# multipart upload. 16 MiB sits above S3's 5 MiB minimum part size by a
# comfortable margin, keeps memory usage bounded (~16 MiB per concurrent
# task), and keeps part count low even for multi-GiB files (a 50 GiB file
# = ~3200 parts, well under S3's 10k limit).
_DRIVE_IMPORT_CHUNK_SIZE = 16 * 1024 * 1024


@shared_task
def deactivate_expired_transfers_task():
    """Deactivate transfers whose expiry date has passed.

    One of three deactivation feeds (alongside manual deactivation and
    first-download auto-archive). All three go through
    ``Transfer.deactivate`` and differ only by the ``deactivation_reason``
    they record — the grace window + actual S3 purge is owned by
    ``delete_pending_transfer_files_task``.
    """
    now = timezone.now()
    transfers_to_deactivate = Transfer.objects.filter(
        status=TransferStatus.ACTIVE,
        expires_at__lte=now,
    )

    count = 0
    for transfer in transfers_to_deactivate:
        transfer.deactivate(DeactivationReason.EXPIRED)

        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_DEACTIVATED_AFTER_EXPIRY,
            actor_type=ActorType.AGENT,
        )
        count += 1

    if count:
        logger.info("Deactivated %d expired transfer(s).", count)


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
def import_drive_file_task(transfer_file_id):
    """Stream a public Drive permalink into our S3 multipart.

    The ``TransferFile`` row is expected to already exist with ``source_url``
    set and ``upload_completed_at`` still null. On success the row's
    ``s3_key`` / ``upload_id`` / ``upload_completed_at`` are populated so
    it looks indistinguishable from a browser-uploaded file. On failure the
    row is deleted — the frontend's poller notices the disappearance and
    surfaces a generic error; the user can re-pick from Drive to retry.
    Any already-initiated S3 multipart is aborted as part of cleanup.
    """
    try:
        tf = TransferFile.objects.get(id=transfer_file_id)
    except TransferFile.DoesNotExist:
        return

    if tf.upload_completed_at is not None:
        # Idempotency: a re-enqueued task for a row that already landed is
        # a no-op rather than a duplicate import.
        return

    key = tf.s3_key or f"transfers/{tf.id}/{tf.filename}"
    upload_id = ""
    try:
        with requests.get(tf.source_url, stream=True, timeout=60) as response:
            response.raise_for_status()

            upload_id = s3.create_multipart_upload(
                key=key, content_type=tf.mime_type or ""
            )
            # Persist the in-flight upload id so an admin / the cleanup cron
            # can abort it if this worker crashes mid-stream.
            tf.s3_key = key
            tf.upload_id = upload_id
            tf.save(update_fields=["s3_key", "upload_id", "updated_at"])

            parts = []
            part_number = 1
            total_bytes = 0
            buffer = bytearray()
            for chunk in response.iter_content(chunk_size=_DRIVE_IMPORT_CHUNK_SIZE):
                if not chunk:
                    continue
                buffer.extend(chunk)
                # Drive may return small chunks; coalesce up to the target
                # size before shipping a part to S3 to avoid hitting the 5
                # MiB minimum on any part except the last.
                while len(buffer) >= _DRIVE_IMPORT_CHUNK_SIZE:
                    part_bytes = bytes(buffer[:_DRIVE_IMPORT_CHUNK_SIZE])
                    del buffer[:_DRIVE_IMPORT_CHUNK_SIZE]
                    etag = s3.upload_part_bytes(
                        key=key,
                        upload_id=upload_id,
                        part_number=part_number,
                        body=part_bytes,
                    )
                    parts.append({"PartNumber": part_number, "ETag": etag})
                    part_number += 1
                    total_bytes += len(part_bytes)

            # Flush the tail — may be smaller than the min part size, which
            # is OK because it is the last part.
            if buffer:
                part_bytes = bytes(buffer)
                etag = s3.upload_part_bytes(
                    key=key,
                    upload_id=upload_id,
                    part_number=part_number,
                    body=part_bytes,
                )
                parts.append({"PartNumber": part_number, "ETag": etag})
                total_bytes += len(part_bytes)

        if total_bytes != tf.size:
            raise ValueError(
                f"Drive returned {total_bytes} bytes but file declared {tf.size}."
            )

        s3.complete_multipart_upload(key=key, upload_id=upload_id, parts=parts)

        tf.upload_id = ""
        tf.upload_completed_at = timezone.now()
        tf.save(update_fields=["upload_id", "upload_completed_at", "updated_at"])
    except (
        requests.RequestException,
        botocore.exceptions.ClientError,
        ValueError,
    ):
        logger.exception("Drive import failed for TransferFile %s", transfer_file_id)
        if upload_id:
            s3.abort_multipart_upload(key=key, upload_id=upload_id)
        # delete_object is safe on a key that never got fully written — S3
        # returns 204 on a non-existent key.
        if tf.s3_key:
            s3.delete_object(tf.s3_key)
        tf.delete()


@shared_task
def delete_pending_transfer_files_task():
    """Wipe S3 objects for transfers whose grace period has elapsed.

    Single feed: every row flagged ``PENDING_FILE_DELETION`` with a past
    ``pending_deletion_at`` — regardless of *why* it got deactivated
    (manual, expiry, first-download; carried by ``deactivation_reason``).
    The grace window between "link closed" and "bytes gone" lets
    recipients' in-flight downloads finish before the bytes disappear.
    After the wipe the row transitions ``PENDING_FILE_DELETION →
    DEACTIVATED`` and ``pending_deletion_at`` is null-ified so the sweep
    is idempotent.
    """
    now = timezone.now()
    to_purge = Transfer.objects.filter(
        status=TransferStatus.PENDING_FILE_DELETION,
        pending_deletion_at__lte=now,
    ).prefetch_related("files")

    count = 0
    for transfer in to_purge:
        deleted_files = list(transfer.files.all())

        transfer.delete_s3_objects()

        transfer.status = TransferStatus.DEACTIVATED
        transfer.deactivated_at = now
        transfer.pending_deletion_at = None
        transfer.save(
            update_fields=[
                "status",
                "deactivated_at",
                "pending_deletion_at",
                "updated_at",
            ]
        )

        TransferEvent.objects.bulk_create(
            TransferEvent(
                transfer_id=transfer.id,
                event_type=TransferEventType.FILE_DELETED,
                actor_type=ActorType.AGENT,
                payload={"file_id": str(f.id), "filename": f.filename},
            )
            for f in deleted_files
        )
        count += 1

    if count:
        logger.info("Deleted files of %d transfer(s).", count)


@shared_task
def send_recipient_invitations_task(transfer_id):
    """Send invitation emails to all recipients of an email-mode transfer."""
    try:
        transfer = Transfer.objects.select_related("owner").get(id=transfer_id)
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
