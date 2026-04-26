"""Structural-leak tests — kept as ``xfail strict`` to document holes that
require code changes (see each test's class docstring for the specific
fix needed).

Each test exercises a real failure mode and asserts the bucket is clean.
None of them pass today: the leaks are real. When a fix lands, remove
the ``@pytest.mark.xfail(...)`` line from the matching test so it turns
into a regular green test that protects against regression.

``strict=True`` means: if a test starts passing without the marker being
removed, pytest fails loudly. So we never silently lose coverage of a
once-known leak.
"""

from unittest.mock import patch

from django.conf import settings
from django.utils import timezone

import botocore
import pytest

from core.factories import TransferDraftFactory, TransferFactory, TransferFileFactory
from core.models import TransferFile
from core.tests._s3_live import assert_bucket_empty, seed_mpu

DRAFTS_URL = "/api/v1.0/drafts/"


@pytest.mark.django_db
class TestRollbackOrphanMPU:
    """``add-file`` (viewsets/draft.py) calls ``s3.create_multipart_upload``
    *inside* its ``transaction.atomic()`` block, then ``tf.save()`` right
    after. The save is wrapped in a try/except that aborts the freshly-created
    MPU before re-raising, so the DB rollback can't leave an orphan in S3.
    """

    def test_save_failure_after_mpu_created_leaves_no_orphan(
        self, authenticated_client, live_s3_bucket
    ):
        bucket = settings.TRANSFERS_BUCKET_NAME

        # Force TransferFile.save() to blow up *after* create_multipart_upload
        # has succeeded — same shape as a transient DB hiccup mid-add-file.
        # patch.object restores the original method automatically on exit,
        # so the assert below queries through a clean ORM.
        def _raise_on_save(self, *args, **kwargs):
            raise RuntimeError("simulated DB hiccup post-MPU-create")

        with patch.object(TransferFile, "save", _raise_on_save):
            try:
                authenticated_client.post(
                    f"{DRAFTS_URL}add-file/",
                    {"filename": "x.bin", "size": 5 * 1024 * 1024},
                    format="json",
                )
            except RuntimeError:
                pass  # the rollback path is what we are testing

        assert_bucket_empty(live_s3_bucket, bucket)


@pytest.mark.django_db
class TestRemoveFileBestEffort:
    """``remove-file`` is best-effort: an S3 failure must not block the DB
    detach. The orphan-sweep is the recovery path for any bytes left.
    """

    def test_abort_failure_does_not_block_remove_file(
        self, authenticated_client, partial_mpu_file, live_s3_bucket
    ):
        forced = botocore.exceptions.ClientError(
            {"Error": {"Code": "InternalError", "Message": "transient"}},
            "AbortMultipartUpload",
        )
        with patch.object(
            live_s3_bucket, "abort_multipart_upload", side_effect=forced
        ):
            resp = authenticated_client.post(
                f"{DRAFTS_URL}{partial_mpu_file['draft_id']}/remove-file/",
                {"transfer_file_id": partial_mpu_file["transfer_file_id"]},
                format="json",
            )

        assert resp.status_code == 204
        assert not TransferFile.objects.filter(
            id=partial_mpu_file["transfer_file_id"]
        ).exists()


@pytest.mark.django_db
class TestDirectORMDelete:
    """There is no ``pre_delete`` signal on ``TransferFile``. Code that
    deletes via the ORM directly (Django admin bulk action, cleanup script,
    future feature, cascade from a parent we forgot about) bypasses every
    S3 cleanup path that lives in the viewsets and tasks.

    Fix path is debatable: keep the ORM "cheap" and require admins to use
    a service method (status quo, but undocumented), OR add a ``pre_delete``
    signal that calls into ``core.services.s3`` (idiomatic, but couples
    every delete to a network call). This test documents the current gap
    so whoever picks the fix has to make an explicit decision.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="no pre_delete signal — direct ORM delete leaves S3 untouched",
    )
    def test_orm_delete_completed_file_clears_bucket(
        self, user, live_s3_bucket
    ):
        bucket = settings.TRANSFERS_BUCKET_NAME
        transfer = TransferFactory(owner=user)
        key = f"transfers/{transfer.id}/orm-deleted.bin"
        live_s3_bucket.put_object(Bucket=bucket, Key=key, Body=b"data")
        tf = TransferFileFactory(
            transfer=transfer, s3_key=key, upload_completed_at=timezone.now()
        )

        # Direct ORM delete — bypasses every viewset / service method.
        tf.delete()

        assert_bucket_empty(live_s3_bucket, bucket)

    @pytest.mark.xfail(
        strict=True,
        reason="no pre_delete signal — direct ORM delete leaves S3 untouched",
    )
    def test_orm_delete_partial_file_clears_bucket(
        self, user, live_s3_bucket
    ):
        bucket = settings.TRANSFERS_BUCKET_NAME
        draft = TransferDraftFactory(owner=user)
        key = f"transfers/{draft.id}/orm-deleted-partial.bin"
        upload_id = seed_mpu(live_s3_bucket, bucket, key, n_parts=1)
        tf = TransferFileFactory(
            transfer=None, draft=draft, s3_key=key, upload_id=upload_id
        )

        tf.delete()

        assert_bucket_empty(live_s3_bucket, bucket)
