"""S3 client factory and multipart upload helpers for the transferts bucket."""

import logging
from functools import cache

from django.conf import settings

import boto3
import botocore

logger = logging.getLogger(__name__)


def _build_client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", None) or "us-east-1",
        config=botocore.client.Config(
            signature_version=getattr(settings, "AWS_S3_SIGNATURE_VERSION", "s3v4"),
        ),
    )


@cache
def get_s3_client():
    """Return the boto3 S3 client for the transfers bucket.

    Cached at module scope: the first call builds the client (and its HTTP
    connection pool), subsequent calls return the same instance so keep-alive
    is effective.
    """
    return _build_client(settings.AWS_S3_ENDPOINT_URL)


@cache
def _get_presigning_client():
    """Return the client used to generate presigned URLs.

    In dev, backend and frontend may see the object storage on different
    hostnames (``objectstorage:9000`` vs ``localhost:8906``). Signatures are
    tied to the hostname, so presigned URLs generated against the internal
    hostname are unusable from the browser. ``AWS_S3_DOMAIN_REPLACE`` lets us
    generate signatures against the browser-facing hostname.
    """
    replace_domain_url = getattr(settings, "AWS_S3_DOMAIN_REPLACE", None)
    if not replace_domain_url:
        return get_s3_client()
    return _build_client(replace_domain_url)


# -- Multipart upload helpers --


def create_multipart_upload(key: str, content_type: str = "") -> str:
    """Initiate an S3 multipart upload. Returns the ``UploadId``."""
    client = get_s3_client()
    response = client.create_multipart_upload(
        Bucket=settings.TRANSFERS_BUCKET_NAME,
        Key=key,
        ContentType=content_type or "application/octet-stream",
    )
    return response["UploadId"]


def sign_upload_part(key: str, upload_id: str, part_number: int) -> str:
    """Return a presigned URL for uploading a single part via HTTP PUT."""
    client = _get_presigning_client()
    return client.generate_presigned_url(
        ClientMethod="upload_part",
        Params={
            "Bucket": settings.TRANSFERS_BUCKET_NAME,
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=settings.TRANSFER_PRESIGNED_URL_EXPIRY,
    )


def sign_download_url(key: str, filename: str, content_type: str = "") -> str:
    """Return a presigned GET URL that triggers a browser download.

    ``ResponseContentDisposition`` is baked into the signature so S3 echoes it
    back as a response header: the browser treats the response as a file
    download, stays on the current page, and uses ``filename`` as the saved
    name. Same for ``ResponseContentType``.
    """
    client = _get_presigning_client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": settings.TRANSFERS_BUCKET_NAME,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
            "ResponseContentType": content_type or "application/octet-stream",
        },
        ExpiresIn=settings.TRANSFER_PRESIGNED_URL_EXPIRY,
    )


def upload_part_bytes(key: str, upload_id: str, part_number: int, body: bytes) -> str:
    """Upload a single part of a multipart upload server-side. Returns the
    part's ``ETag`` as a double-quoted string, ready to feed back to
    ``complete_multipart_upload``.

    This is the server-side counterpart of ``sign_upload_part`` — used by
    the Drive-import celery task, where bytes flow through the backend
    rather than being PUT directly by the browser.
    """
    client = get_s3_client()
    response = client.upload_part(
        Bucket=settings.TRANSFERS_BUCKET_NAME,
        Key=key,
        UploadId=upload_id,
        PartNumber=part_number,
        Body=body,
    )
    return response["ETag"]


def complete_multipart_upload(key: str, upload_id: str, parts: list[dict]) -> None:
    """Finalize a multipart upload given the list of uploaded parts.

    ``parts`` is a list of ``{"PartNumber": int, "ETag": str}`` dicts. The order
    does not matter — it is sorted by ``PartNumber`` before being sent to S3.
    """
    ordered_parts = sorted(parts, key=lambda p: p["PartNumber"])
    client = get_s3_client()
    client.complete_multipart_upload(
        Bucket=settings.TRANSFERS_BUCKET_NAME,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": ordered_parts},
    )


def abort_multipart_upload(key: str, upload_id: str) -> None:
    """Abort a multipart upload. Raises ``ClientError`` on failure — for
    best-effort sweeps over many files, use ``abort_uploads_for_files``."""
    client = get_s3_client()
    client.abort_multipart_upload(
        Bucket=settings.TRANSFERS_BUCKET_NAME,
        Key=key,
        UploadId=upload_id,
    )


def delete_object(key: str) -> None:
    """Delete a single object. Raises ``ClientError`` on failure — for
    best-effort sweeps over many files, use ``delete_objects_for_files``."""
    client = get_s3_client()
    client.delete_object(Bucket=settings.TRANSFERS_BUCKET_NAME, Key=key)


def head_object_size(key: str) -> int:
    """Return the actual size (ContentLength) of an object in the bucket."""
    client = get_s3_client()
    response = client.head_object(Bucket=settings.TRANSFERS_BUCKET_NAME, Key=key)
    return int(response["ContentLength"])


def abort_uploads_for_files(files) -> None:
    """Best-effort abort across ``files`` (queryset or list). Files without
    ``upload_id`` are skipped; per-file ``ClientError`` is logged and
    swallowed so one bad MPU does not abort the sweep."""
    for tf in files:
        if not tf.upload_id:
            continue
        try:
            abort_multipart_upload(tf.s3_key, tf.upload_id)
        except botocore.exceptions.ClientError:
            logger.exception(
                "Failed to abort multipart upload %s for key %s",
                tf.upload_id,
                tf.s3_key,
            )


def delete_objects_for_files(files) -> None:
    """Best-effort delete across ``files`` (queryset or list). Files without
    ``s3_key`` are skipped; per-file ``ClientError`` is logged and swallowed."""
    for tf in files:
        if not tf.s3_key:
            continue
        try:
            delete_object(tf.s3_key)
        except botocore.exceptions.ClientError:
            logger.exception("Failed to delete S3 object %s", tf.s3_key)
