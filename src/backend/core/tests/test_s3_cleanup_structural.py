"""Structural-leak tests — each exercises a real failure mode of the
draft / multipart-upload flow and asserts the bucket is clean (or the
DB row is detached) afterwards.
"""

from unittest.mock import patch

from django.conf import settings

import botocore
import pytest

from core.models import TransferFile
from core.tests._s3_live import assert_bucket_empty

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
