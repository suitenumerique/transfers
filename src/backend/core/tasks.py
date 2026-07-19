"""Celery tasks for the transferts core app."""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import botocore
import requests
import sentry_sdk
from celery import shared_task

from core.enums import (
    ActorType,
    DeactivationReason,
    ScanStatus,
    TransferEventType,
    TransferStatus,
)
from core.models import Transfer, TransferDraft, TransferEvent, TransferFile
from core.services import encryption, s3
from core.services.email import send_recipient_invitation
from core.services.s3_sweep import run_orphan_sweep

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
        # deactivate() returns False when another feed (manual / first
        # download) already moved the row out of ACTIVE between the query
        # above and now. Only record the expiry audit event when the transfer gets
        # deactivated HERE, otherwise the log would claim an expiry that never
        # happened.
        if not transfer.deactivate(DeactivationReason.EXPIRED):
            continue

        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_DEACTIVATED_AFTER_EXPIRY,
            actor_type=ActorType.AGENT,
        )
        count += 1

    if count:
        logger.info("Deactivated %d expired transfer(s).", count)


@shared_task
def sweep_orphan_s3_storage_task():
    """Daily safety net for S3 leaks not caught by the per-row cleanup paths.

    Should report zero in steady state — non-zero counts are the signal
    that one of the per-row paths is leaking.
    """
    result = run_orphan_sweep(
        apply=True,
        min_age_hours=24,
        write=lambda msg: logger.info("orphan-sweep: %s", msg),
        write_error=lambda msg: logger.error("orphan-sweep: %s", msg),
    )
    if result["objects_deleted"] or result["mpus_aborted"]:
        logger.warning(
            "orphan-sweep cleaned %d object(s) and %d MPU(s) — investigate "
            "which per-row path leaked",
            result["objects_deleted"],
            result["mpus_aborted"],
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
    # Snapshot the ids first; we re-fetch each draft under SELECT FOR UPDATE
    # so a concurrent finalize / abort / add_file blocks instead of racing
    # us into deleting bytes that just got reparented.
    abandoned_ids = list(
        TransferDraft.objects.filter(created_at__lte=cutoff).values_list(
            "id", flat=True
        )
    )

    count = 0
    for draft_id in abandoned_ids:
        with transaction.atomic():
            try:
                draft = TransferDraft.objects.select_for_update().get(
                    id=draft_id, created_at__lte=cutoff
                )
            except TransferDraft.DoesNotExist:
                # Finalized or aborted between the snapshot and now.
                continue
            files = list(draft.files.all())
            s3.best_effort_abort_multipart_uploads_from_files(files)
            s3.best_effort_delete_objects_from_files(files)
            draft.delete()
            count += 1

    if count:
        logger.info("Cleaned up %d abandoned draft(s).", count)


@shared_task
def import_drive_file_task(transfer_file_id):
    """Stream a public Drive permalink into our S3 multipart, encrypting it.

    Runs during finalize (non-confidential transfers only, so we hold the
    key). The bytes are fetched server-to-server, re-chunked into the
    transfer's crypto chunk size, and each chunk is AES-GCM encrypted with
    the key parked on the draft before enqueueing — so a Drive file is
    indistinguishable from a browser-encrypted upload and the recipient SW
    decrypts it the same way. The key is read from ``tf.draft.encryption_key``
    rather than passed as a Celery kwarg, keeping it out of task metadata
    and broker payloads.

    On success ``upload_completed_at`` is set and the row stays PENDING, so the
    finalize gate submits its scan. On failure ``import_failed_at`` is set and
    the row is kept, so the finalize poll can surface it to the user.
    """
    try:
        tf = TransferFile.objects.get(id=transfer_file_id)
    except TransferFile.DoesNotExist:
        return

    if tf.upload_completed_at is not None:
        # Idempotency: a re-enqueued task for a row that already landed is
        # a no-op rather than a duplicate import.
        return

    # The import runs at finalize while the file is still on the draft (the
    # Transfer is created only once every Drive import has completed). The
    # draft's chunk size is the value the client used to declare the
    # ciphertext ``size``, so encrypting with it is what makes the produced
    # object match; the settings fallback is a safety net.
    chunk_size = (
        tf.draft.encryption_chunk_size
        if tf.draft and tf.draft.encryption_chunk_size
        else settings.TRANSFER_CHUNK_SIZE
    )
    encryption_key = tf.draft.encryption_key if tf.draft else ""
    key = tf.s3_key or f"transfers/{tf.id}/{tf.filename}"
    upload_id = ""
    try:
        aes_key = encryption.decode_key(encryption_key)

        with requests.get(tf.source_url, stream=True, timeout=60) as response:
            response.raise_for_status()

            # Reject up front on the declared size, then cap what we actually
            # read (the header may be missing or lying). Otherwise we'd encrypt
            # and ship an unbounded body to S3 before the final check caught it.
            declared = response.headers.get("Content-Length")
            try:
                declared = int(declared) if declared else None
            except ValueError:
                declared = None
            if declared is not None and declared > tf.plaintext_size:
                raise ValueError(
                    f"Drive declared {declared} plaintext bytes but file "
                    f"declared plaintext_size={tf.plaintext_size}."
                )

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
            total_plaintext = 0
            total_ciphertext = 0
            buffer = bytearray()

            def _encrypt_and_upload(plaintext: bytes) -> None:
                nonlocal part_number, total_plaintext, total_ciphertext
                body = encryption.encrypt_chunk(
                    aes_key, plaintext, str(tf.id), part_number
                )
                etag = s3.upload_part_bytes(
                    key=key,
                    upload_id=upload_id,
                    part_number=part_number,
                    body=body,
                )
                parts.append({"PartNumber": part_number, "ETag": etag})
                part_number += 1
                total_plaintext += len(plaintext)
                total_ciphertext += len(body)

            downloaded = 0
            for chunk in response.iter_content(chunk_size=_DRIVE_IMPORT_CHUNK_SIZE):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > tf.plaintext_size:
                    raise ValueError(
                        f"Drive stream exceeded the declared "
                        f"plaintext_size={tf.plaintext_size} (Content-Length "
                        f"missing or understated)."
                    )
                buffer.extend(chunk)
                # One crypto chunk = one S3 part. Coalesce Drive's arbitrary
                # read sizes into full ``chunk_size`` plaintext blocks so the
                # ciphertext layout matches what the browser produces (and
                # every part but the last clears S3's 5 MiB minimum).
                while len(buffer) >= chunk_size:
                    _encrypt_and_upload(bytes(buffer[:chunk_size]))
                    del buffer[:chunk_size]

            # Flush the tail (the shorter last chunk). For an exact
            # non-zero multiple of chunk_size the buffer is already empty —
            # the last full chunk shipped inside the loop, matching the
            # browser which emits no empty trailing chunk. Zero-byte
            # plaintext is the special case: the browser still ships one
            # chunk (just IV + tag, ``CRYPTO_OVERHEAD_PER_CHUNK`` bytes)
            # so ``tf.size == 28``; ship the same here or the ciphertext
            # size check below would fail with a 0-vs-28 mismatch.
            if buffer or tf.plaintext_size == 0:
                _encrypt_and_upload(bytes(buffer))

        if total_plaintext != tf.plaintext_size:
            raise ValueError(
                f"Drive returned {total_plaintext} plaintext bytes but file "
                f"declared plaintext_size={tf.plaintext_size}."
            )
        if total_ciphertext != tf.size:
            raise ValueError(
                f"Encrypted to {total_ciphertext} bytes but file declared "
                f"size={tf.size}."
            )

        s3.complete_multipart_upload(key=key, upload_id=upload_id, parts=parts)

        tf.upload_id = ""
        tf.upload_completed_at = timezone.now()
        # Drive implies non-confidential, so we hold the key and this object
        # is scannable. The row stays PENDING (the model default) so the
        # finalize scan-submission loop picks it up on the next poll — same
        # code path as browser uploads. The scan-exempt statuses are set
        # here for the shortcuts (scan disabled instance-wide, file over
        # the scanner cap) so the finalize gate lets the transfer through.
        update_fields = ["upload_id", "upload_completed_at", "updated_at"]
        if not settings.CLAMAV_SCAN_ENABLED:
            tf.scan_status = ScanStatus.SKIPPED
            update_fields.append("scan_status")
        elif tf.size > settings.SCAN_MAX_FILE_SIZE:
            tf.scan_status = ScanStatus.TOO_LARGE
            update_fields.append("scan_status")
        tf.save(update_fields=update_fields)
    except Exception:
        # Catch broadly: any failure between create_multipart_upload and the
        # final save (DB hiccup, S3 error, size mismatch, bad key…) needs the
        # same cleanup, otherwise the MPU and partial object leak. Report the
        # original exception to Sentry before the cleanup runs — abort /
        # delete calls can raise their own ClientError and would otherwise
        # take over the active exception context here.
        sentry_sdk.capture_exception()
        logger.exception("Drive import failed for TransferFile %s", transfer_file_id)
        if upload_id:
            try:
                s3.abort_multipart_upload(key=key, upload_id=upload_id)
            except botocore.exceptions.ClientError:
                logger.exception("Failed to abort MPU %s for key %s", upload_id, key)
        # delete_object is idempotent on missing keys (S3 returns 204).
        if tf.s3_key:
            try:
                s3.delete_object(tf.s3_key)
            except botocore.exceptions.ClientError:
                logger.exception("Failed to delete object %s", tf.s3_key)
        # Keep the row and mark it failed so the finalize poll can surface
        # the failure; the user removes the file (or re-picks to retry).
        tf.upload_id = ""
        tf.import_failed_at = timezone.now()
        tf.save(update_fields=["upload_id", "import_failed_at", "updated_at"])


class ScanNotPossible(Exception):
    """This file cannot be meaningfully scanned, so it must not be submitted."""


def _scan_encryption_params(tf):
    """What the scanner needs to decrypt ``tf``.

    Fail closed: scanning an encrypted object without these doesn't error out —
    clamd reports the opaque bytes CLEAN. Everything we store is encrypted, so
    anything we can't assemble decryption material for is a bug, not a plaintext
    file, and must not be scanned. Read the state from the row's actual parent,
    not the draft alone, so a reparented file can't pass as plaintext.
    """
    parent = tf.draft or tf.transfer
    if parent is None:
        raise ScanNotPossible("row has neither draft nor transfer")

    if parent.encryption_chunk_size is None:
        raise ScanNotPossible("no chunk size — cannot decrypt")

    if not parent.encryption_key:
        # No key yet (finalize supplies it), or confidential — never any key.
        raise ScanNotPossible("encrypted, no key available")

    return {
        "key": parent.encryption_key,
        "chunk_size": parent.encryption_chunk_size,
        # AAD prefix — must match what the browser bound each chunk to.
        "file_id": str(tf.id),
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def submit_scan_task(self, transfer_file_id):
    """Submit a completed file to the file-scanner service for a virus scan.

    Fire-and-forget from the caller's view: we hand the scanner a presigned
    GET URL for the file plus a callback URL carrying a per-file secret, and
    the result lands later on the scan-result webhook (which flips
    ``scan_status``). The file stays ``PENDING`` — and thus undownloadable —
    until then.

    No-ops cleanly when scanning is disabled, when the file row has vanished
    (uploaded then removed before the task ran), or when the upload never
    actually completed. Only the HTTP submit is retried; once the scanner has
    accepted the job, delivery of the result is the webhook's problem.
    """
    if not settings.CLAMAV_SCAN_ENABLED:
        return
    if not settings.CLAMAV_SERVICE_URL or not settings.SCAN_WEBHOOK_BASE_URL:
        logger.error(
            "Scan enabled but CLAMAV_SERVICE_URL / SCAN_WEBHOOK_BASE_URL unset; "
            "skipping scan for %s",
            transfer_file_id,
        )
        return

    try:
        tf = TransferFile.objects.get(id=transfer_file_id)
    except TransferFile.DoesNotExist:
        # Uploaded then deleted before the scan was submitted — nothing to do.
        return

    if tf.upload_completed_at is None:
        # Upload not finished (or was rolled back) — don't scan a partial object.
        return

    if tf.scan_status != ScanStatus.PENDING:
        # Already resolved (or a retry/rescan racing a verdict that just landed)
        # — don't launch a redundant scan. Correctness is enforced by the
        # PENDING-guarded webhook; this just avoids the wasted scanner work.
        return

    # Mint the per-file callback secret on first submit; reuse it on retries so
    # the webhook URL stays stable across attempts. The conditional update only
    # matches while the secret is still empty, so concurrent submissions (e.g. a
    # reaper re-submit racing the initial one) converge on a single value instead
    # of each minting its own.
    if not tf.webhook_secret:
        TransferFile.objects.filter(id=tf.id, webhook_secret="").update(
            webhook_secret=secrets.token_urlsafe(32), updated_at=timezone.now()
        )
        tf.refresh_from_db(fields=["webhook_secret"])

    try:
        encryption_params = _scan_encryption_params(tf)
    except ScanNotPossible as exc:
        logger.info("Not scanning TransferFile %s: %s", transfer_file_id, exc)
        return

    scan_url = s3.sign_scan_url(tf.s3_key)
    webhook_url = (
        f"{settings.SCAN_WEBHOOK_BASE_URL}/api/{settings.API_VERSION}"
        f"/webhooks/scan-result/?file_id={tf.id}&secret={tf.webhook_secret}"
    )

    payload = {
        "url": scan_url,
        "filename": tf.filename,
        "webhook_url": webhook_url,
    }
    if encryption_params:
        payload["encryption"] = encryption_params

    try:
        response = requests.post(
            f"{settings.CLAMAV_SERVICE_URL}/v2/scan-async",
            json=payload,
            headers={"X-API-Key": settings.CLAMAV_API_KEY},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "Scan submission failed for TransferFile %s: %s", transfer_file_id, exc
        )
        raise self.retry(exc=exc) from exc

    job_id = ""
    try:
        job_id = response.json().get("job_id", "")
    except ValueError:
        logger.warning("Scanner returned a non-JSON body for %s", transfer_file_id)

    # Targeted update: the row may have been concurrently mutated and we only
    # own the scan_job_id column here.
    TransferFile.objects.filter(id=tf.id).update(scan_job_id=job_id)
    logger.info("Submitted scan for TransferFile %s (job %s)", transfer_file_id, job_id)


@shared_task
def reap_stale_pending_scans_task():
    """Re-submit scans that never came back (lost webhook, dead worker),
    otherwise the file stays PENDING — and undownloadable — forever.

    Clocked on ``scan_submitted_at``, not the upload: a scan only starts at
    finalize, which can be long after the bytes landed.
    """
    if not settings.CLAMAV_SCAN_ENABLED:
        return

    now = timezone.now()
    cutoff = now - timedelta(minutes=settings.SCAN_PENDING_REAP_MINUTES)
    stale = TransferFile.objects.filter(
        scan_status=ScanStatus.PENDING,
        scan_submitted_at__isnull=False,
        scan_submitted_at__lte=cutoff,
    ).values_list("id", flat=True)

    count = 0
    for file_id in stale:
        submit_scan_task.delay(str(file_id))
        # Bump the timestamp only after the enqueue succeeds so the row
        # stays visible to the next tick if the broker rejected us. The
        # updated value keeps the same row from being re-reaped on every
        # subsequent tick while the (re-submitted) scan is running.
        TransferFile.objects.filter(id=file_id).update(
            scan_submitted_at=now, updated_at=now
        )
        count += 1

    if count:
        logger.info("Re-submitted %d stale pending scan(s).", count)


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
        # Isolate each transfer: a DB failure on save / bulk_create must not
        # abort the whole batch. The row stays PENDING_FILE_DELETION and is
        # retried on the next run (delete_s3_objects is idempotent). count is
        # only bumped once the status flip + events commit successfully.
        try:
            deleted_files = list(transfer.files.all())

            if not transfer.delete_s3_objects():
                # At least one object failed to delete. Flipping to
                # DEACTIVATED here would strand those bytes forever: the
                # orphan sweep can't reclaim them while the TransferFile
                # rows still list the keys as known. Leave the row
                # PENDING_FILE_DELETION so the next run retries the wipe.
                logger.warning(
                    "Transfer %s: some S3 objects failed to delete; "
                    "leaving it PENDING_FILE_DELETION for the next run",
                    transfer.id,
                )
                continue

            with transaction.atomic():
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
        except Exception:
            logger.exception(
                "Failed to purge transfer %s; leaving it for the next run",
                transfer.id,
            )
            continue

    if count:
        logger.info("Deleted files of %d transfer(s).", count)


@shared_task
def send_recipient_invitations_task(transfer_id):
    """Send invitation emails to every recipient of ``transfer_id`` that
    doesn't have an ``email_sent_at`` yet.

    The email carries only the download link, never the decryption key.
    A non-confidential transfer's key is served by the backend at
    download time; a confidential transfer's key never reaches us (the
    sender delivers it out of band). Either way no decryption material
    reaches this task or the outbound email body.
    """
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

    # Stamp completion regardless of per-recipient outcome — the frontend
    # uses this to leave its "sending…" polling state, and a partial failure
    # is signalled by recipients with email_sent_at IS NULL after the stamp.
    transfer.notifications_completed_at = timezone.now()
    transfer.save(update_fields=["notifications_completed_at", "updated_at"])
