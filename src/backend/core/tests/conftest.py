"""Shared test fixtures and helpers."""

from unittest.mock import MagicMock, patch

from django.conf import settings as django_settings

import pytest
from moto import mock_aws
from rest_framework.test import APIClient

from core.enums import ScanStatus
from core.factories import TransferFactory, TransferFileFactory, UserFactory
from core.models import TransferEvent, TransferFile
from core.services import s3 as s3_module
from core.tests._s3_live import S3_MIN_PART_SIZE


def _head_matching_declared_size(key):
    """Default stub for ``s3.head_object_size``: return whatever size the
    TransferFile was created with, so the post-complete-upload size check
    passes on the happy path. Tests that simulate a size mismatch override
    ``head.return_value`` or ``head.side_effect`` to force a divergence."""
    return TransferFile.objects.get(s3_key=key).size


@pytest.fixture
def patched_s3():
    """Patch every ``core.services.s3`` helper used by the draft and
    transfer viewsets.

    Patching at the service module means both viewsets see the mock (they
    both ``from core.services import s3``). Yields a MagicMock whose
    attributes expose each individual mock for assertions.
    """
    with (
        patch(
            "core.services.s3.create_multipart_upload",
            return_value="FAKE-UPLOAD-ID",
        ) as create_mock,
        patch(
            "core.services.s3.sign_upload_part",
            return_value="https://s3.example.com/part-url",
        ) as sign_mock,
        patch("core.services.s3.complete_multipart_upload") as complete_mock,
        patch("core.services.s3.abort_multipart_upload") as abort_mock,
        patch("core.services.s3.delete_object") as delete_mock,
        patch(
            "core.services.s3.head_object_size",
            side_effect=_head_matching_declared_size,
        ) as head_mock,
    ):
        yield MagicMock(
            create=create_mock,
            sign=sign_mock,
            complete=complete_mock,
            abort=abort_mock,
            delete=delete_mock,
            head=head_mock,
        )


def assert_single_event(transfer_id, event_type, **payload_checks):
    """Assert exactly one event exists for this transfer, with the given type and payload."""
    events = TransferEvent.objects.filter(transfer_id=transfer_id)
    assert events.count() == 1
    event = events.first()
    assert event.event_type == event_type
    for key, value in payload_checks.items():
        assert event.payload[key] == value


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authenticated_client(user, api_client):
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def transfer(user):
    return TransferFactory(owner=user)


@pytest.fixture
def transfer_with_file(transfer):
    from django.utils import timezone as _tz

    TransferFileFactory(
        transfer=transfer,
        filename="doc.pdf",
        size=1024,
        upload_completed_at=_tz.now(),
        # A finalized transfer's files have passed the scan gate (CLEAN /
        # SKIPPED / TOO_LARGE) — never PENDING. Default to CLEAN so the
        # unconditional download gate lets them through.
        scan_status=ScanStatus.CLEAN,
    )
    return transfer


# --- Live S3 fixtures (moto-backed, opt-in) -----------------------------
# `patched_s3` above mocks every helper and asserts on call signatures —
# it can never catch "called abort but the bucket still has bytes". The
# fixtures below boot moto in-process so a test can run the real code path
# and assert on actual bucket state. They are deliberately separate so that
# existing tests stay on the cheap mock and only cleanup tests pay the
# moto setup cost.


@pytest.fixture
def live_s3_bucket(monkeypatch):
    """Yield a boto3 S3 client wired to an in-process moto backend with
    the transfers bucket pre-created.

    Function-scoped so each test gets a clean bucket. The ``mock_aws()``
    context wraps boto3 globally, so any code path under test that
    constructs an S3 client lands on moto. We override the relevant
    ``settings.AWS_S3_*`` and clear the ``@cache`` on
    ``s3.get_s3_client`` / ``s3._get_presigning_client`` so the
    application code rebuilds its client against the mock.
    """
    bucket = django_settings.TRANSFERS_BUCKET_NAME
    with mock_aws():
        # ``endpoint_url=None`` makes boto3 use the standard AWS hostname,
        # which is what moto's HTTP interceptor recognises. A custom URL
        # (e.g. "http://moto-mock:5000") would bypass moto and try a real
        # TCP connect — which is what we don't want in unit tests.
        monkeypatch.setattr(django_settings, "AWS_S3_ENDPOINT_URL", None)
        monkeypatch.setattr(django_settings, "AWS_S3_ACCESS_KEY_ID", "test")
        monkeypatch.setattr(django_settings, "AWS_S3_SECRET_ACCESS_KEY", "test")
        monkeypatch.setattr(django_settings, "AWS_S3_REGION_NAME", "us-east-1")
        monkeypatch.setattr(django_settings, "AWS_S3_DOMAIN_REPLACE", None)

        # Wipe whatever the previous test cached — without this the app code
        # would keep using a client pointing at the old (now torn-down) mock
        # endpoint.
        s3_module.get_s3_client.cache_clear()
        s3_module._get_presigning_client.cache_clear()

        client = s3_module.get_s3_client()
        client.create_bucket(Bucket=bucket)

        yield client

    # Belt-and-braces: leaving the cache populated with a dead client would
    # poison any test that runs next without `live_s3_bucket`.
    s3_module.get_s3_client.cache_clear()
    s3_module._get_presigning_client.cache_clear()


@pytest.fixture
def partial_mpu_file(authenticated_client, live_s3_bucket):
    """Open a draft and seed one file in the in-progress MPU state (1 part
    uploaded, no complete-upload). Returns the full add-file response dict.

    The most common shape under test: a user dropped a file, started
    uploading, hasn't finished — now something cancels.
    """
    resp = authenticated_client.post(
        "/api/v1.0/drafts/add-file/",
        {"filename": "x.bin", "size": S3_MIN_PART_SIZE},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    live_s3_bucket.upload_part(
        Bucket=django_settings.TRANSFERS_BUCKET_NAME,
        Key=resp.data["s3_key"],
        UploadId=resp.data["upload_id"],
        PartNumber=1,
        Body=b"y" * S3_MIN_PART_SIZE,
    )
    return dict(resp.data)


@pytest.fixture
def completed_file(authenticated_client, live_s3_bucket):
    """Open a draft, upload one part, and complete the MPU end-to-end.
    Returns the add-file response dict (with ``upload_id`` already cleared
    in DB after the complete-upload call).
    """
    resp = authenticated_client.post(
        "/api/v1.0/drafts/add-file/",
        {"filename": "y.bin", "size": S3_MIN_PART_SIZE},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    bucket = django_settings.TRANSFERS_BUCKET_NAME
    part = live_s3_bucket.upload_part(
        Bucket=bucket,
        Key=resp.data["s3_key"],
        UploadId=resp.data["upload_id"],
        PartNumber=1,
        Body=b"y" * S3_MIN_PART_SIZE,
    )
    complete = authenticated_client.post(
        f"/api/v1.0/drafts/{resp.data['draft_id']}/complete-upload/",
        {
            "transfer_file_id": resp.data["transfer_file_id"],
            "parts": [{"PartNumber": 1, "ETag": part["ETag"]}],
        },
        format="json",
    )
    assert complete.status_code == 204, complete.data
    return dict(resp.data)
