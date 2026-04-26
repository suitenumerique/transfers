"""Integration tests — bucket-state assertions for draft cleanup paths.

Each test exercises a real cleanup path end-to-end through the API against
a moto-backed bucket, and asserts the bucket is *actually* empty after.
The terminal assertion is always ``assert_bucket_empty`` — that's the
single contract these tests enforce.

The mock-based equivalents in ``test_api_drafts.py`` only prove that the
right S3 helpers were *called*. These tests prove the bytes are gone.
"""

from django.conf import settings

import pytest

from core.tests._s3_live import S3_MIN_PART_SIZE, assert_bucket_empty

DRAFTS_URL = "/api/v1.0/drafts/"


@pytest.mark.django_db
class TestRemoveFileLeaks:
    """POST /drafts/{id}/remove-file/ — must clean up S3 for both the
    in-progress (MPU still open) and completed (object sealed) cases."""

    def test_remove_partial_file_clears_mpu(
        self, authenticated_client, partial_mpu_file, live_s3_bucket
    ):
        resp = authenticated_client.post(
            f"{DRAFTS_URL}{partial_mpu_file['draft_id']}/remove-file/",
            {"transfer_file_id": partial_mpu_file["transfer_file_id"]},
            format="json",
        )
        assert resp.status_code == 204, resp.data
        assert_bucket_empty(live_s3_bucket, settings.TRANSFERS_BUCKET_NAME)

    def test_remove_completed_file_clears_object(
        self, authenticated_client, completed_file, live_s3_bucket
    ):
        resp = authenticated_client.post(
            f"{DRAFTS_URL}{completed_file['draft_id']}/remove-file/",
            {"transfer_file_id": completed_file["transfer_file_id"]},
            format="json",
        )
        assert resp.status_code == 204, resp.data
        assert_bucket_empty(live_s3_bucket, settings.TRANSFERS_BUCKET_NAME)


@pytest.mark.django_db
class TestAbortDraftLeaks:
    """POST /drafts/{id}/abort/ — must clean up every file in the draft,
    regardless of which lifecycle stage each file is in."""

    def test_abort_clears_partial_only(
        self, authenticated_client, partial_mpu_file, live_s3_bucket
    ):
        resp = authenticated_client.post(
            f"{DRAFTS_URL}{partial_mpu_file['draft_id']}/abort/", {}, format="json"
        )
        assert resp.status_code == 204, resp.data
        assert_bucket_empty(live_s3_bucket, settings.TRANSFERS_BUCKET_NAME)

    def test_abort_clears_mixed_partial_and_completed(
        self, authenticated_client, partial_mpu_file, live_s3_bucket
    ):
        # Attach a second file and complete it, so the draft mixes one
        # in-progress MPU with one sealed object — the most realistic shape
        # for a user changing their mind mid-batch.
        bucket = settings.TRANSFERS_BUCKET_NAME
        add_resp = authenticated_client.post(
            f"{DRAFTS_URL}add-file/",
            {
                "draft_id": partial_mpu_file["draft_id"],
                "filename": "second.bin",
                "size": S3_MIN_PART_SIZE,
            },
            format="json",
        )
        assert add_resp.status_code == 201, add_resp.data
        part = live_s3_bucket.upload_part(
            Bucket=bucket,
            Key=add_resp.data["s3_key"],
            UploadId=add_resp.data["upload_id"],
            PartNumber=1,
            Body=b"z" * S3_MIN_PART_SIZE,
        )
        complete_resp = authenticated_client.post(
            f"{DRAFTS_URL}{partial_mpu_file['draft_id']}/complete-upload/",
            {
                "transfer_file_id": add_resp.data["transfer_file_id"],
                "parts": [{"PartNumber": 1, "ETag": part["ETag"]}],
            },
            format="json",
        )
        assert complete_resp.status_code == 204, complete_resp.data

        resp = authenticated_client.post(
            f"{DRAFTS_URL}{partial_mpu_file['draft_id']}/abort/", {}, format="json"
        )
        assert resp.status_code == 204, resp.data
        assert_bucket_empty(live_s3_bucket, bucket)


@pytest.mark.django_db
class TestCompleteUploadLeaks:
    """POST /drafts/{id}/complete-upload/ — failure paths must drop *every*
    file's S3 state (whole-draft teardown), per the all-or-nothing contract
    in the viewset docstring."""

    def test_size_mismatch_clears_whole_draft(
        self, authenticated_client, partial_mpu_file, live_s3_bucket
    ):
        # The fixture uploads exactly 5 MiB; we declared 5 MiB. To force a
        # mismatch we attach a *second* file with a declared size that the
        # client will not match, then complete it after uploading the wrong
        # number of bytes.
        bucket = settings.TRANSFERS_BUCKET_NAME
        add_resp = authenticated_client.post(
            f"{DRAFTS_URL}add-file/",
            {
                "draft_id": partial_mpu_file["draft_id"],
                "filename": "wrong-size.bin",
                "size": 2 * S3_MIN_PART_SIZE,  # declare double what we'll upload
            },
            format="json",
        )
        assert add_resp.status_code == 201, add_resp.data
        # Upload only one min-size part — head_object_size surfaces the mismatch.
        part = live_s3_bucket.upload_part(
            Bucket=bucket,
            Key=add_resp.data["s3_key"],
            UploadId=add_resp.data["upload_id"],
            PartNumber=1,
            Body=b"a" * S3_MIN_PART_SIZE,
        )
        resp = authenticated_client.post(
            f"{DRAFTS_URL}{partial_mpu_file['draft_id']}/complete-upload/",
            {
                "transfer_file_id": add_resp.data["transfer_file_id"],
                "parts": [{"PartNumber": 1, "ETag": part["ETag"]}],
            },
            format="json",
        )
        assert resp.status_code == 400, resp.data

        # Per the viewset docstring, a size-mismatch is an all-or-nothing
        # teardown: the whole draft is nuked, including the *other* file
        # that was perfectly fine.
        assert_bucket_empty(live_s3_bucket, bucket)

    def test_s3_completion_error_clears_whole_draft(
        self, authenticated_client, partial_mpu_file, live_s3_bucket
    ):
        # Pass a bogus ETag — moto rejects CompleteMultipartUpload with a
        # ClientError, which the viewset translates into the all-or-nothing
        # teardown of the draft.
        bucket = settings.TRANSFERS_BUCKET_NAME
        resp = authenticated_client.post(
            f"{DRAFTS_URL}{partial_mpu_file['draft_id']}/complete-upload/",
            {
                "transfer_file_id": partial_mpu_file["transfer_file_id"],
                "parts": [{"PartNumber": 1, "ETag": '"deadbeef"'}],
            },
            format="json",
        )
        assert resp.status_code == 400, resp.data
        assert_bucket_empty(live_s3_bucket, bucket)
