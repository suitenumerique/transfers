"""Tests for the Transfer API endpoints (authenticated agent)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

import pytest

from core.enums import TransferEventType, TransferStatus
from core.factories import TransferFactory
from core.models import Transfer, TransferEvent
from core.tests.conftest import assert_single_event

API_URL = "/api/v1.0/transfers/"


@pytest.mark.django_db
class TestTransferList:
    def test_unauthenticated(self, api_client):
        response = api_client.get(API_URL)
        assert response.status_code == 401

    def test_list_own_transfers(self, authenticated_client, user):
        TransferFactory(owner=user)
        TransferFactory(owner=user)
        TransferFactory()  # another user's transfer

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 2

    def test_list_empty(self, authenticated_client):
        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 0


@pytest.mark.django_db
class TestTransferDetail:
    def test_retrieve(self, authenticated_client, transfer):
        response = authenticated_client.get(f"{API_URL}{transfer.id}/")
        assert response.status_code == 200
        assert response.data["id"] == str(transfer.id)
        assert response.data["public_token"] == transfer.public_token

    def test_retrieve_other_user(self, authenticated_client):
        other_transfer = TransferFactory()
        response = authenticated_client.get(f"{API_URL}{other_transfer.id}/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestTransferCreate:
    @patch("core.api.viewsets.transfer._get_s3_client")
    def test_create_transfer(self, mock_s3, authenticated_client, user):
        mock_s3.return_value = MagicMock()

        file = SimpleUploadedFile("doc.pdf", b"pdf-content", content_type="application/pdf")

        response = authenticated_client.post(
            API_URL,
            {
                "title": "My transfer",
                "expires_in_days": 30,
                "file": file,
            },
            format="multipart",
        )

        assert response.status_code == 201
        assert response.data["title"] == "My transfer"
        assert len(response.data["files"]) == 1
        assert response.data["status"] == "active"

        transfer = Transfer.objects.get(id=response.data["id"])
        assert transfer.owner == user

        assert_single_event(transfer.id, TransferEventType.TRANSFER_CREATED)

    @patch("core.api.viewsets.transfer._get_s3_client")
    def test_create_with_custom_expiry(self, mock_s3, authenticated_client):
        mock_s3.return_value = MagicMock()

        file = SimpleUploadedFile("doc.pdf", b"content", content_type="application/pdf")
        response = authenticated_client.post(
            API_URL,
            {
                "expires_in_days": 90,
                "file": file,
            },
            format="multipart",
        )

        assert response.status_code == 201
        transfer = Transfer.objects.get(id=response.data["id"])
        expected_min = timezone.now() + timedelta(days=89)
        assert transfer.expires_at > expected_min

    def test_create_no_file(self, authenticated_client):
        response = authenticated_client.post(
            API_URL,
            {},
            format="multipart",
        )
        assert response.status_code == 400

    @patch("core.api.viewsets.transfer._get_s3_client")
    def test_create_invalid_expiry(self, mock_s3, authenticated_client):
        mock_s3.return_value = MagicMock()

        file = SimpleUploadedFile("doc.pdf", b"content", content_type="application/pdf")
        response = authenticated_client.post(
            API_URL,
            {
                "expires_in_days": 999,
                "file": file,
            },
            format="multipart",
        )
        assert response.status_code == 400

    @patch("core.api.viewsets.transfer._get_s3_client")
    def test_create_sensitive(self, mock_s3, authenticated_client):
        mock_s3.return_value = MagicMock()

        file = SimpleUploadedFile("doc.pdf", b"content", content_type="application/pdf")
        response = authenticated_client.post(
            API_URL,
            {
                "sensitive": True,
                "file": file,
            },
            format="multipart",
        )

        assert response.status_code == 201
        transfer = Transfer.objects.get(id=response.data["id"])
        assert transfer.sensitive is True


@pytest.mark.django_db
class TestTransferRevoke:
    @patch("core.api.viewsets.transfer._delete_transfer_files_from_s3")
    def test_revoke(self, mock_delete_s3, authenticated_client, transfer):
        response = authenticated_client.post(f"{API_URL}{transfer.id}/revoke/")

        assert response.status_code == 200
        assert response.data["status"] == "revoked"
        assert response.data["revoked_at"] is not None
        mock_delete_s3.assert_called_once()

        assert_single_event(transfer.id, TransferEventType.TRANSFER_REVOKED)

    def test_revoke_already_revoked(self, authenticated_client, transfer):
        transfer.status = TransferStatus.REVOKED
        transfer.save(update_fields=["status"])

        response = authenticated_client.post(f"{API_URL}{transfer.id}/revoke/")
        assert response.status_code == 400

    def test_revoke_other_user(self, authenticated_client):
        other_transfer = TransferFactory()
        response = authenticated_client.post(f"{API_URL}{other_transfer.id}/revoke/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestTransferReactivate:
    def test_reactivate_expired(self, authenticated_client, transfer):
        transfer.status = TransferStatus.EXPIRED
        transfer.expires_at = timezone.now() - timedelta(hours=1)
        transfer.save(update_fields=["status", "expires_at"])
        old_token = transfer.public_token

        response = authenticated_client.post(f"{API_URL}{transfer.id}/reactivate/")

        assert response.status_code == 200
        assert response.data["status"] == "active"
        assert response.data["public_token"] == old_token  # same token kept

    def test_reactivate_active_fails(self, authenticated_client, transfer):
        response = authenticated_client.post(f"{API_URL}{transfer.id}/reactivate/")
        assert response.status_code == 400

    def test_reactivate_revoked_fails(self, authenticated_client, transfer):
        transfer.status = TransferStatus.REVOKED
        transfer.save(update_fields=["status"])

        response = authenticated_client.post(f"{API_URL}{transfer.id}/reactivate/")
        assert response.status_code == 400


@pytest.mark.django_db
class TestTransferEvents:
    def test_list_events(self, authenticated_client, transfer):
        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_CREATED,
            actor_type="agent",
            actor_id=transfer.owner.id,
        )

        response = authenticated_client.get(f"{API_URL}{transfer.id}/events/")
        assert response.status_code == 200
        assert response.data["count"] == 1
