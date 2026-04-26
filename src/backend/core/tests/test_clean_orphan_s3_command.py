"""Integration tests — the ``clean_orphan_s3_objects`` management command.

The command is the manual sweep we run when we suspect leaks have crept
in. It diffs S3 against ``TransferFile.s3_key`` rows and deletes objects
that no row points to. It does NOT scan in-progress multipart uploads
today — that gap is documented as ``xfail strict``.
"""

from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

import pytest

from core.factories import TransferFactory, TransferFileFactory
from core.tests._s3_live import (
    assert_bucket_empty,
    count_objects,
    seed_mpu,
    seed_object,
)


@pytest.mark.django_db
class TestCleanOrphanObjects:
    """Happy-path coverage of the existing scan."""

    def test_dry_run_lists_orphans_without_deleting(self, user, live_s3_bucket):
        bucket = settings.TRANSFERS_BUCKET_NAME
        # Two objects in S3 — only one has a DB row pointing to it.
        seed_object(live_s3_bucket, bucket, "transfers/known/a.bin")
        seed_object(live_s3_bucket, bucket, "transfers/orphan/b.bin")
        TransferFileFactory(
            transfer=TransferFactory(owner=user),
            s3_key="transfers/known/a.bin",
            upload_completed_at=timezone.now(),
        )

        out = StringIO()
        call_command("clean_orphan_s3_objects", stdout=out)

        # Dry-run = nothing actually deleted.
        assert count_objects(live_s3_bucket, bucket) == 2
        assert "Would delete 1 orphan(s)" in out.getvalue()

    def test_apply_deletes_orphans_only(self, user, live_s3_bucket):
        bucket = settings.TRANSFERS_BUCKET_NAME
        seed_object(live_s3_bucket, bucket, "transfers/known/a.bin")
        seed_object(live_s3_bucket, bucket, "transfers/orphan/b.bin")
        seed_object(live_s3_bucket, bucket, "transfers/orphan/c.bin")
        TransferFileFactory(
            transfer=TransferFactory(owner=user),
            s3_key="transfers/known/a.bin",
            upload_completed_at=timezone.now(),
        )

        call_command("clean_orphan_s3_objects", "--apply", stdout=StringIO())

        remaining = {
            o["Key"]
            for o in live_s3_bucket.list_objects_v2(Bucket=bucket).get("Contents")
            or []
        }
        assert remaining == {"transfers/known/a.bin"}


@pytest.mark.django_db
class TestCleanOrphanMPUs:
    """Coverage of the *missing* MPU scan — the command's biggest blind
    spot. The current implementation only iterates completed objects via
    ``list_objects_v2``, so any in-progress multipart upload that no DB
    row references (e.g. survivors of a worker crash) stays forever.

    Fix: add a second pass that calls ``list_multipart_uploads``,
    cross-references against ``TransferFile.objects.exclude(upload_id="")``,
    and aborts the difference.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="command never lists multipart uploads — orphan MPUs are invisible to it",
    )
    def test_apply_aborts_orphan_mpus(self, live_s3_bucket):
        bucket = settings.TRANSFERS_BUCKET_NAME
        # An MPU in S3 with no DB row — the kind a crashed worker leaves
        # behind. The command should detect and abort it.
        seed_mpu(live_s3_bucket, bucket, "transfers/orphan-mpu/x.bin", n_parts=2)

        call_command("clean_orphan_s3_objects", "--apply", stdout=StringIO())

        assert_bucket_empty(live_s3_bucket, bucket)
