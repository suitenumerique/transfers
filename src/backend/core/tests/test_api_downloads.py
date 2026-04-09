"""Tests for the download API endpoints (no auth)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

from core.enums import TransferEventType, TransferStatus
from core.factories import (
    TransferFactory,
    TransferFileFactory,
)
from core.tests.conftest import assert_single_event

DOWNLOADS_URL = "/api/v1.0/downloads"


@pytest.mark.django_db
class TestDownloadTransferView:
    def test_get_transfer_without_password(self, api_client, transfer_with_files):
        """Transfer without password returns full data."""
        t = transfer_with_files
        url = f"{DOWNLOADS_URL}/{t.public_token}/"

        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data["title"] == t.title
        assert len(response.data["files"]) == 2
        assert response.data["has_password"] is False
        assert "owner_name" in response.data
        assert "owner_email" in response.data
        assert "message" in response.data

        assert_single_event(t.id, TransferEventType.LINK_OPENED)

    def test_get_transfer_with_password_returns_locked(self, api_client):
        """Transfer with password returns only minimal info."""
        t = TransferFactory()
        t.set_password("secret")
        t.save()

        response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/")
        assert response.status_code == 200
        assert response.data["has_password"] is True
        assert response.data["title"] == t.title
        # Only title and has_password should be present
        assert set(response.data.keys()) == {"title", "has_password"}

    def test_get_expired_transfer(self, api_client):
        t = TransferFactory(expires_at=timezone.now() - timedelta(hours=1))
        response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/")
        assert response.status_code == 403

    def test_get_revoked_transfer(self, api_client):
        t = TransferFactory(status=TransferStatus.REVOKED)
        response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/")
        assert response.status_code == 403

    def test_get_nonexistent_token(self, api_client):
        response = api_client.get(f"{DOWNLOADS_URL}/nonexistent-token/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestDownloadVerifyPassword:
    def test_correct_password_returns_full_data(self, api_client):
        """Successful password verification returns full transfer data."""
        t = TransferFactory()
        t.set_password("secret")
        t.save()

        response = api_client.post(
            f"{DOWNLOADS_URL}/{t.public_token}/verify-password/",
            {"password": "secret"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["title"] == t.title
        assert "files" in response.data
        assert "message" in response.data
        assert "owner_email" in response.data

        assert_single_event(t.id, TransferEventType.PASSWORD_ATTEMPT, success=True)

    def test_wrong_password(self, api_client):
        t = TransferFactory()
        t.set_password("secret")
        t.save()

        response = api_client.post(
            f"{DOWNLOADS_URL}/{t.public_token}/verify-password/",
            {"password": "wrong"},
            format="json",
        )
        assert response.status_code == 403

        assert_single_event(t.id, TransferEventType.PASSWORD_ATTEMPT, success=False)

    def test_verify_on_expired(self, api_client):
        t = TransferFactory(expires_at=timezone.now() - timedelta(hours=1))
        t.set_password("secret")
        t.save()

        response = api_client.post(
            f"{DOWNLOADS_URL}/{t.public_token}/verify-password/",
            {"password": "secret"},
            format="json",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestDownloadFileView:
    @patch("core.api.viewsets.download._get_s3_client")
    def test_download_file(self, mock_s3, api_client, transfer_with_files):
        t = transfer_with_files
        tf = t.files.first()

        mock_body = MagicMock()
        mock_body.iter_chunks.return_value = [b"file-content"]
        mock_s3.return_value.get_object.return_value = {"Body": mock_body}

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/"
        )
        assert response.status_code == 200
        assert response["Content-Disposition"] == f'attachment; filename="{tf.filename}"'

        assert_single_event(t.id, TransferEventType.FILE_DOWNLOADED)

    @patch("core.api.viewsets.download._get_s3_client")
    def test_download_with_password(self, mock_s3, api_client):
        t = TransferFactory()
        t.set_password("secret")
        t.save()
        tf = TransferFileFactory(transfer=t)

        mock_body = MagicMock()
        mock_body.iter_chunks.return_value = [b"content"]
        mock_s3.return_value.get_object.return_value = {"Body": mock_body}

        # Without password
        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/"
        )
        assert response.status_code == 403

        # With correct password
        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/?password=secret"
        )
        assert response.status_code == 200

    def test_download_nonexistent_file(self, api_client, transfer):
        import uuid

        response = api_client.get(
            f"{DOWNLOADS_URL}/{transfer.public_token}/files/{uuid.uuid4()}/download/"
        )
        assert response.status_code == 404

    def test_download_from_expired(self, api_client):
        t = TransferFactory(expires_at=timezone.now() - timedelta(hours=1))
        tf = TransferFileFactory(transfer=t)

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/"
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestDownloadAll:
    @patch("core.api.viewsets.download._get_s3_client")
    def test_download_all_zip(self, mock_s3, api_client, transfer_with_files):
        t = transfer_with_files

        mock_body = MagicMock()
        mock_body.read.return_value = b"file-content"
        mock_s3.return_value.get_object.return_value = {"Body": mock_body}

        response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/download-all/")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"

        assert_single_event(t.id, TransferEventType.ALL_FILES_DOWNLOADED)

    @patch("core.api.viewsets.download._get_s3_client")
    def test_download_all_with_password(self, mock_s3, api_client):
        t = TransferFactory()
        t.set_password("secret")
        t.save()
        TransferFileFactory(transfer=t)

        # Without password
        response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/download-all/")
        assert response.status_code == 403

        mock_body = MagicMock()
        mock_body.read.return_value = b"content"
        mock_s3.return_value.get_object.return_value = {"Body": mock_body}

        # With password
        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/download-all/?password=secret"
        )
        assert response.status_code == 200
