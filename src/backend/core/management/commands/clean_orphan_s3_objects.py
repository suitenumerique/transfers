"""Delete S3 objects in the transfers bucket that no TransferFile row points to."""

from django.conf import settings
from django.core.management.base import BaseCommand

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

    def handle(self, *args, **options):
        apply = options["apply"]
        prefix = options["prefix"]
        bucket = settings.TRANSFERS_BUCKET_NAME

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

        verb = "Deleted" if apply else "Would delete"
        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {scanned} objects. {verb} {deleted} orphan(s)."
            )
        )
        if not apply:
            self.stdout.write("Dry-run only. Re-run with --apply to delete.")

    def _flush(self, client, bucket: str, batch: list[dict]) -> int:
        response = client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        for err in response.get("Errors", []) or []:
            self.stderr.write(
                self.style.ERROR(
                    f"failed to delete {err['Key']}: {err.get('Code')} {err.get('Message')}"
                )
            )
        return len(response.get("Deleted", []) or [])
