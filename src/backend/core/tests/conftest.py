"""Shared test fixtures and helpers."""

import pytest
from rest_framework.test import APIClient

from core.factories import (
    TransferFactory,
    TransferFileFactory,
    TransferRecipientFactory,
    UserFactory,
)
from core.models import TransferEvent


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
def transfer_with_files(transfer):
    TransferFileFactory(transfer=transfer, filename="doc.pdf", size=1024)
    TransferFileFactory(transfer=transfer, filename="photo.jpg", size=2048)
    return transfer


@pytest.fixture
def transfer_with_recipients(transfer):
    TransferRecipientFactory(transfer=transfer, email="alice@example.com")
    TransferRecipientFactory(transfer=transfer, email="bob@example.com")
    return transfer
