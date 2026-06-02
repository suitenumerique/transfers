"""Integration tests — bucket-state assertions for transfer cleanup paths.

Covers the post-finalize teardown: deactivation is a two-step flow —
the link closes immediately (ACTIVE → PENDING_FILE_DELETION) and S3
objects are purged after the grace window by
``delete_pending_transfer_files_task`` (PENDING_FILE_DELETION → DEACTIVATED).
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

import pytest

from core.enums import TransferStatus
from core.factories import TransferFactory, TransferFileFactory
from core.tasks import delete_pending_transfer_files_task
from core.tests._s3_live import assert_bucket_empty


@pytest.mark.django_db
class TestDeactivateLeaks:
    """POST /transfers/{id}/deactivate/ — two-step: flag then purge S3."""

    def test_deactivate_clears_all_objects(
        self, authenticated_client, user, live_s3_bucket
    ):
        bucket = settings.TRANSFERS_BUCKET_NAME
        transfer = TransferFactory(owner=user)
        for i in range(3):
            key = f"transfers/{transfer.id}/file-{i}.bin"
            live_s3_bucket.put_object(Bucket=bucket, Key=key, Body=b"data")
            TransferFileFactory(
                transfer=transfer,
                s3_key=key,
                upload_completed_at=timezone.now(),
            )

        # Step 1: deactivate closes the link, enters grace window.
        resp = authenticated_client.post(
            f"/api/v1.0/transfers/{transfer.id}/deactivate/"
        )
        assert resp.status_code == 200, resp.data

        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.PENDING_FILE_DELETION

        # Step 2: bypass the grace window and run the purge task.
        transfer.pending_deletion_at = timezone.now() - timedelta(seconds=1)
        transfer.save(update_fields=["pending_deletion_at"])
        delete_pending_transfer_files_task()

        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.DEACTIVATED
        assert transfer.deactivated_at is not None
        assert_bucket_empty(live_s3_bucket, bucket)
