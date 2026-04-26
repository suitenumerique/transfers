"""Celery tasks for the transferts core app."""

import logging
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

import botocore
import requests
from celery import shared_task

from core.enums import ActorType, TransferEventType, TransferStatus
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
def sweep_orphan_s3_storage_task():
    """Daily safety net for S3 leaks not caught by the per-row cleanup paths.

    ``--min-age=24`` keeps the sweep clear of the brief orphan window in
    ``add_file`` (between ``s3.create_multipart_upload`` and ``tf.save()``).
    In steady state this should report zero — non-zero output is the signal
    that one of the per-row cleanup paths is leaking.
    """
    call_command(
        "clean_orphan_s3_objects",
        "--apply",
        "--min-age",
        "24",
    )


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
        files = list(draft.files.all())
        s3.abort_uploads_for_files(files)
        s3.delete_objects_for_files(files)
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
        # Best-effort: a S3 cleanup error must not block tf.delete() — the
        # frontend's poller relies on the row disappearing to surface the
        # failure to the user.
        if upload_id:
            try:
                s3.abort_multipart_upload(key=key, upload_id=upload_id)
            except botocore.exceptions.ClientError:
                logger.exception(
                    "Failed to abort MPU %s for key %s", upload_id, key
                )
        # delete_object is idempotent on missing keys (S3 returns 204).
        if tf.s3_key:
            try:
                s3.delete_object(tf.s3_key)
            except botocore.exceptions.ClientError:
                logger.exception("Failed to delete object %s", tf.s3_key)
        tf.delete()


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
