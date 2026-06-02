"""Helpers for S3 cleanup integration tests.

Leading underscore keeps pytest from treating this as a test module. The
helpers operate on a real-ish S3 client (moto-backed in tests) so they can
verify bucket state — what mocks can't do.
"""

# AWS S3's minimum size for any non-final multipart part. moto doesn't
# enforce this on individual UploadPart calls, but real S3 (and Scaleway)
# reject CompleteMultipartUpload with EntityTooSmall if any non-last part
# is below the threshold. We size every test part at exactly the minimum
# so the same fixtures stay portable to a future live-S3 conformance run
# without surprise mid-test failures.
S3_MIN_PART_SIZE = 5 * 1024 * 1024


def assert_bucket_empty(client, bucket: str) -> None:
    """Assert no completed objects AND no in-progress multipart uploads.

    The single source of truth for "did cleanup actually leave the bucket
    clean?". Surfacing both views in one helper means a leak in either path
    fails the test with the same call site.
    """
    objects = client.list_objects_v2(Bucket=bucket).get("Contents", []) or []
    uploads = client.list_multipart_uploads(Bucket=bucket).get("Uploads", []) or []
    assert objects == [], (
        f"bucket {bucket!r} has {len(objects)} leftover object(s): "
        f"{[o['Key'] for o in objects]}"
    )
    assert uploads == [], (
        f"bucket {bucket!r} has {len(uploads)} leftover MPU(s): "
        f"{[(u['Key'], u['UploadId']) for u in uploads]}"
    )


def count_objects(client, bucket: str) -> int:
    return len(client.list_objects_v2(Bucket=bucket).get("Contents", []) or [])


def count_mpus(client, bucket: str) -> int:
    return len(client.list_multipart_uploads(Bucket=bucket).get("Uploads", []) or [])


def seed_object(client, bucket: str, key: str, body: bytes = b"x") -> None:
    """PUT an object directly into the bucket — bypasses the API."""
    client.put_object(Bucket=bucket, Key=key, Body=body)


def seed_mpu(client, bucket: str, key: str, n_parts: int = 1) -> str:
    """Create an MPU with ``n_parts`` parts uploaded. Returns the upload_id.

    Used by orphan-MPU tests that need an in-progress upload to exist
    independent of any DB row.
    """
    upload_id = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
    body = b"y" * S3_MIN_PART_SIZE
    for n in range(1, n_parts + 1):
        client.upload_part(
            Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=n, Body=body
        )
    return upload_id
