"""Clean up S3 storage in the transfers bucket that no TransferFile row points to.

Two passes:
- Completed objects (``list_objects_v2``) → diff against ``TransferFile.s3_key``.
- In-progress multipart uploads (``list_multipart_uploads``) → diff against
  ``TransferFile.upload_id``. MPUs are invisible to the object listing and
  bill storage forever if not aborted; this is what catches survivors of a
  worker crash.

``--min-age`` skips objects/MPUs younger than the cutoff so a scheduled run
can't race with the brief window in ``add_file`` where an MPU exists on S3
before its DB row has landed.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

import botocore

from core.models import TransferFile
from core.services import s3

# S3 caps DeleteObjects at 1000 keys per request.
DELETE_BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Delete objects in the transfers bucket whose key is not referenced by "
        "any TransferFile row. Dry-run by default — pass --apply to delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete orphan objects (default: dry-run).",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Restrict scan to objects under this S3 prefix (e.g. 'transfers/').",
        )
        parser.add_argument(
            "--min-age",
            type=int,
            default=24,
            help=(
                "Skip objects/MPUs younger than N hours (default 24, sized "
                "to clear in-flight uploads). Pass 0 to ignore age."
            ),
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        prefix = options["prefix"]
        min_age_hours = options["min_age"]
        bucket = settings.TRANSFERS_BUCKET_NAME

        cutoff = (
            timezone.now() - timedelta(hours=min_age_hours)
            if min_age_hours > 0
            else None
        )

        known_keys = set(
            TransferFile.objects.exclude(s3_key="").values_list("s3_key", flat=True)
        )
        self.stdout.write(f"DB references {len(known_keys)} S3 keys.")

        client = s3.get_s3_client()
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
                self.stdout.write(f"orphan: {key} ({obj['Size']} bytes)")
                batch.append({"Key": key})
                if apply and len(batch) >= DELETE_BATCH_SIZE:
                    deleted += self._flush(client, bucket, batch)
                    batch = []
                elif not apply:
                    deleted += 1
                    batch = []

        if apply and batch:
            deleted += self._flush(client, bucket, batch)

        mpus_scanned, mpus_aborted = self._scan_mpus(
            client, bucket, prefix, apply, cutoff
        )

        verb = "Deleted" if apply else "Would delete"
        verb_mpu = "Aborted" if apply else "Would abort"
        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {scanned} objects. {verb} {deleted} orphan(s)."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {mpus_scanned} multipart uploads. "
                f"{verb_mpu} {mpus_aborted} orphan MPU(s)."
            )
        )
        if not apply:
            self.stdout.write("Dry-run only. Re-run with --apply to delete.")

    def _scan_mpus(
        self, client, bucket: str, prefix: str, apply: bool, cutoff
    ) -> tuple[int, int]:
        """List in-progress multipart uploads, abort the ones with no DB row.

        Keyed on ``(s3_key, upload_id)`` rather than ``upload_id`` alone — the
        S3 API allows multiple MPUs per key, even if our app never creates that
        shape on purpose.
        """
        known_uploads = set(
            TransferFile.objects.exclude(upload_id="").values_list(
                "s3_key", "upload_id"
            )
        )
        self.stdout.write(f"DB references {len(known_uploads)} in-progress MPU(s).")

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
                self.stdout.write(f"orphan MPU: {key} (upload_id={upload_id})")
                if not apply:
                    aborted += 1
                    continue
                try:
                    client.abort_multipart_upload(
                        Bucket=bucket, Key=key, UploadId=upload_id
                    )
                except botocore.exceptions.ClientError as exc:
                    # One bad MPU shouldn't kill the sweep — log and move on.
                    self.stderr.write(
                        self.style.ERROR(
                            f"failed to abort MPU {key} ({upload_id}): "
                            f"{exc.response.get('Error', {}).get('Code', 'Unknown')} "
                            f"{exc.response.get('Error', {}).get('Message', '')}"
                        )
                    )
                    continue
                aborted += 1

        return scanned, aborted

    def _flush(self, client, bucket: str, batch: list[dict]) -> int:
        response = client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        for err in response.get("Errors", []) or []:
            self.stderr.write(
                self.style.ERROR(
                    f"failed to delete {err['Key']}: {err.get('Code')} {err.get('Message')}"
                )
            )
        return len(response.get("Deleted", []) or [])
