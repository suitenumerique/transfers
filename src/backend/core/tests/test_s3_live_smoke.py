"""Smoke test: verify the live_s3_bucket fixture wires up moto correctly."""

from django.conf import settings

import pytest

from core.tests._s3_live import assert_bucket_empty, count_mpus, count_objects, seed_mpu


def test_bucket_starts_empty(live_s3_bucket):
    assert_bucket_empty(live_s3_bucket, settings.TRANSFERS_BUCKET_NAME)


def test_seed_mpu_then_abort_leaves_bucket_empty(live_s3_bucket):
    bucket = settings.TRANSFERS_BUCKET_NAME
    upload_id = seed_mpu(live_s3_bucket, bucket, "k/leak", n_parts=2)
    assert count_mpus(live_s3_bucket, bucket) == 1
    live_s3_bucket.abort_multipart_upload(
        Bucket=bucket, Key="k/leak", UploadId=upload_id
    )
    assert_bucket_empty(live_s3_bucket, bucket)


@pytest.mark.django_db
def test_partial_mpu_fixture_yields_in_progress_upload(
    partial_mpu_file, live_s3_bucket
):
    bucket = settings.TRANSFERS_BUCKET_NAME
    assert count_mpus(live_s3_bucket, bucket) == 1
    assert count_objects(live_s3_bucket, bucket) == 0
    assert partial_mpu_file["upload_id"]
    assert partial_mpu_file["s3_key"].startswith("transfers/")


@pytest.mark.django_db
def test_completed_file_fixture_seals_object(completed_file, live_s3_bucket):
    bucket = settings.TRANSFERS_BUCKET_NAME
    assert count_mpus(live_s3_bucket, bucket) == 0
    assert count_objects(live_s3_bucket, bucket) == 1
