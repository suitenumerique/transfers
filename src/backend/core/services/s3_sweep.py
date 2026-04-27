"""Orphan-sweep orchestration: cross-reference S3 against ``TransferFile``
rows and delete/abort what no row points to.

Single source of truth for the two-pass sweep — used by the manual
operator command (``clean_orphan_s3_objects``) and by the daily Celery
task ``sweep_orphan_s3_storage_task``.
"""

from datetime import timedelta
from typing import Callable

from django.conf import settings
from django.utils import timezone

import botocore

from core.models import TransferFile
from core.services import s3

# S3 caps DeleteObjects at 1000 keys per request.
DELETE_BATCH_SIZE = 1000

Writer = Callable[[str], None]


def _noop(_: str) -> None:
    return None


def run_orphan_sweep(
    *,
    apply: bool,
    min_age_hours: int,
    prefix: str = "",
    write: Writer = _noop,
    write_error: Writer = _noop,
) -> dict:
    """Run the two-pass orphan sweep against the transfers bucket.

    ``write`` and ``write_error`` route per-orphan / per-failure lines to
    the caller's preferred sink (CLI stdout, Python logger, etc.). The
    final summary is the caller's responsibility — compose it from the
    returned dict so the caller controls formatting and styling.

    Returns a dict with keys ``objects_scanned``, ``objects_deleted``,
    ``mpus_scanned``, ``mpus_aborted``. Under dry-run the *_deleted /
    *_aborted counters report what *would* happen.
    """
    bucket = settings.TRANSFERS_BUCKET_NAME
    cutoff = (
        timezone.now() - timedelta(hours=min_age_hours)
        if min_age_hours > 0
        else None
    )

    client = s3.get_s3_client()
    objects_scanned, objects_deleted = _scan_objects(
        client, bucket, prefix, apply, cutoff, write, write_error
    )
    mpus_scanned, mpus_aborted = _scan_mpus(
        client, bucket, prefix, apply, cutoff, write, write_error
    )

    return {
        "objects_scanned": objects_scanned,
        "objects_deleted": objects_deleted,
        "mpus_scanned": mpus_scanned,
        "mpus_aborted": mpus_aborted,
    }


def _scan_objects(
    client, bucket: str, prefix: str, apply: bool, cutoff, write, write_error
) -> tuple[int, int]:
    known_keys = set(
        TransferFile.objects.exclude(s3_key="").values_list("s3_key", flat=True)
    )
    write(f"DB references {len(known_keys)} S3 keys.")

    paginator = client.get_paginator("list_objects_v2")
    scanned = 0
    deleted = 0
    batch: list[dict] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            scanned += 1
            key = obj["Key"]
            if key in known_keys:
                continue
            if cutoff is not None and obj["LastModified"] > cutoff:
                continue
            write(f"orphan: {key} ({obj['Size']} bytes)")
            batch.append({"Key": key})
            if apply and len(batch) >= DELETE_BATCH_SIZE:
                deleted += _flush_batch(client, bucket, batch, write_error)
                batch = []
            elif not apply:
                deleted += 1
                batch = []

    if apply and batch:
        deleted += _flush_batch(client, bucket, batch, write_error)

    return scanned, deleted


def _scan_mpus(
    client, bucket: str, prefix: str, apply: bool, cutoff, write, write_error
) -> tuple[int, int]:
    """Keyed on ``(s3_key, upload_id)`` rather than ``upload_id`` alone — the
    S3 API allows multiple MPUs per key, even if our app never creates that
    shape on purpose.
    """
    known_uploads = set(
        TransferFile.objects.exclude(upload_id="").values_list(
            "s3_key", "upload_id"
        )
    )
    write(f"DB references {len(known_uploads)} in-progress MPU(s).")

    paginator = client.get_paginator("list_multipart_uploads")
    scanned = 0
    aborted = 0

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for upload in page.get("Uploads", []) or []:
            scanned += 1
            key = upload["Key"]
            upload_id = upload["UploadId"]
            if (key, upload_id) in known_uploads:
                continue
            if cutoff is not None and upload["Initiated"] > cutoff:
                continue
            write(f"orphan MPU: {key} (upload_id={upload_id})")
            if not apply:
                aborted += 1
                continue
            try:
                client.abort_multipart_upload(
                    Bucket=bucket, Key=key, UploadId=upload_id
                )
            except botocore.exceptions.ClientError as exc:
                # One bad MPU shouldn't kill the sweep — log and move on.
                write_error(
                    f"failed to abort MPU {key} ({upload_id}): "
                    f"{exc.response.get('Error', {}).get('Code', 'Unknown')} "
                    f"{exc.response.get('Error', {}).get('Message', '')}"
                )
                continue
            aborted += 1

    return scanned, aborted


def _flush_batch(client, bucket: str, batch: list[dict], write_error: Writer) -> int:
    response = client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
    for err in response.get("Errors", []) or []:
        write_error(
            f"failed to delete {err['Key']}: "
            f"{err.get('Code')} {err.get('Message')}"
        )
    return len(response.get("Deleted", []) or [])
