"""S3 client factory and multipart upload helpers for the transferts bucket.

Two-tier helper API:

- Bare ``abort_multipart_upload`` / ``delete_object`` raise ``ClientError`` —
  use them when the caller needs to surface or react to a failure.
- ``best_effort_abort_multipart_uploads_from_files`` /
  ``best_effort_delete_objects_from_files`` iterate over ``TransferFile``
  rows and swallow ``ClientError`` per item — use them when one bad file
  must not stop the sweep.
"""

import logging
from functools import cache
from urllib.parse import quote

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
    hostnames (``objectstorage:9000`` vs ``localhost:8986``). Signatures are
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


def _content_disposition(filename: str) -> str:
    """Build an RFC 6266 ``Content-Disposition`` value for ``filename``.

    A user-supplied filename can contain quotes, control chars or non-ASCII
    (``report.pdf"; filename=invoice.exe``), which would break out of a naive
    ``filename="…"`` token and let a sender spoof the saved name. We emit an
    ASCII-sanitised ``filename`` token (quotes/backslashes/control chars
    stripped) for legacy clients plus a percent-encoded ``filename*`` that
    carries the exact UTF-8 name for modern browsers, which take precedence.
    """
    ascii_fallback = (
        filename.encode("ascii", "ignore")
        .decode("ascii")
        .replace("\\", "")
        .replace('"', "")
    )
    # Strip control characters that would otherwise survive the ASCII encode.
    ascii_fallback = "".join(c for c in ascii_fallback if c >= " ") or "download"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


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
            "ResponseContentDisposition": _content_disposition(filename),
            "ResponseContentType": content_type or "application/octet-stream",
        },
        ExpiresIn=settings.TRANSFER_PRESIGNED_URL_EXPIRY,
    )


def sign_scan_url(key: str) -> str:
    """Return a presigned GET URL for the antivirus scanner to fetch the file.

    Signed with the *internal* client (``get_s3_client`` → ``AWS_S3_ENDPOINT_URL``),
    NOT the browser-facing ``_get_presigning_client``. The scanner runs as a
    container on the shared Docker network and reaches the object storage at
    its internal hostname (``objectstorage:9000`` in dev); a URL signed against
    the browser host (``localhost:8906``) would be unreachable from inside the
    scanner container. In prod both clients resolve to the same public endpoint,
    so this is equivalent there.

    Uses a dedicated, longer TTL than a browser download: the scan request may
    sit in the scanner's own queue before the file is actually fetched.
    """
    client = get_s3_client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": settings.TRANSFERS_BUCKET_NAME,
            "Key": key,
        },
        ExpiresIn=settings.SCAN_PRESIGNED_URL_EXPIRY,
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
    best-effort sweeps over many files, use
    ``best_effort_abort_multipart_uploads_from_files``."""
    client = get_s3_client()
    client.abort_multipart_upload(
        Bucket=settings.TRANSFERS_BUCKET_NAME,
        Key=key,
        UploadId=upload_id,
    )


def delete_object(key: str) -> None:
    """Delete a single object. Raises ``ClientError`` on failure — for
    best-effort sweeps over many files, use
    ``best_effort_delete_objects_from_files``."""
    client = get_s3_client()
    client.delete_object(Bucket=settings.TRANSFERS_BUCKET_NAME, Key=key)


def head_object_size(key: str) -> int:
    """Return the actual size (ContentLength) of an object in the bucket."""
    client = get_s3_client()
    response = client.head_object(Bucket=settings.TRANSFERS_BUCKET_NAME, Key=key)
    return int(response["ContentLength"])


def best_effort_abort_multipart_uploads_from_files(files) -> None:
    """Best-effort abort across ``files`` (queryset or list of ``TransferFile``).
    Files without ``upload_id`` are skipped; per-file ``ClientError`` is logged
    and swallowed so one bad MPU does not abort the sweep."""
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


def best_effort_delete_objects_from_files(files) -> bool:
    """Best-effort delete across ``files`` (queryset or list of ``TransferFile``).
    Files without ``s3_key`` are skipped; per-file ``ClientError`` is logged
    and swallowed.

    Returns ``True`` iff every object with an ``s3_key`` was deleted without
    error — callers that own a data-deletion guarantee (the purge task) use
    this to decide whether the row may move to its terminal DEACTIVATED state
    or must stay PENDING_FILE_DELETION for a retry.
    """
    all_deleted = True
    for tf in files:
        if not tf.s3_key:
            continue
        try:
            delete_object(tf.s3_key)
        except botocore.exceptions.ClientError:
            logger.exception("Failed to delete S3 object %s", tf.s3_key)
            all_deleted = False
    return all_deleted
