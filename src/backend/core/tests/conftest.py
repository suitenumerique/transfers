"""Shared test fixtures and helpers."""

from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from core.factories import TransferFactory, TransferFileFactory, UserFactory
from core.models import TransferEvent, TransferFile


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
    )
    return transfer
