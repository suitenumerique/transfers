"""Integration tests — bucket-state assertions for transfer cleanup paths.

Covers the post-finalize teardown: the only mutation a Transfer admits is
``deactivate``, which tears down S3 alongside the status flip.
"""

from django.conf import settings
from django.utils import timezone

import pytest

from core.enums import TransferStatus
from core.factories import TransferFactory, TransferFileFactory
from core.tests._s3_live import assert_bucket_empty


@pytest.mark.django_db
class TestDeactivateLeaks:
    """POST /transfers/{id}/deactivate/ — must clear every object backing
    the transfer's files."""

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

        resp = authenticated_client.post(
            f"/api/v1.0/transfers/{transfer.id}/deactivate/"
        )
        assert resp.status_code == 200, resp.data

        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.DEACTIVATED
        assert transfer.deactivated_at is not None
        assert_bucket_empty(live_s3_bucket, bucket)
