"""Tests for the download API endpoints (no auth)."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

import pytest

from core.enums import TransferEventType, TransferStatus
from core.factories import TransferFactory, TransferFileFactory
from core.tests.conftest import assert_single_event

DOWNLOADS_URL = "/api/v1.0/downloads"


@pytest.mark.django_db
class TestDownloadTransferView:
    def test_get_transfer(self, api_client, transfer_with_file):
        t = transfer_with_file
        url = f"{DOWNLOADS_URL}/{t.public_token}/"

        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data["title"] == t.title
        assert len(response.data["files"]) == 1
        assert "owner_name" in response.data
        assert "owner_email" in response.data

        assert_single_event(t.id, TransferEventType.LINK_OPENED)

    def test_get_expired_transfer(self, api_client):
        t = TransferFactory(expires_at=timezone.now() - timedelta(hours=1))
        response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/")
        assert response.status_code == 410

    def test_get_deactivated_transfer(self, api_client):
        t = TransferFactory(status=TransferStatus.DEACTIVATED)
        response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/")
        assert response.status_code == 403
        assert response.data["reason"] == "deactivated"

    def test_get_nonexistent_token(self, api_client):
        response = api_client.get(f"{DOWNLOADS_URL}/nonexistent-token/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestDownloadFileView:
    @patch("core.api.viewsets.download.sign_download_url")
    def test_download_file_redirects(self, mock_sign, api_client, transfer_with_file):
        t = transfer_with_file
        tf = t.files.first()
        mock_sign.return_value = "https://s3.example.com/signed-get-url"

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/"
        )
        assert response.status_code == 302
        assert response["Location"] == "https://s3.example.com/signed-get-url"
        mock_sign.assert_called_once_with(tf.s3_key, tf.filename, tf.mime_type)

        assert_single_event(t.id, TransferEventType.FILE_DOWNLOADED)

    def test_download_nonexistent_file(self, api_client, transfer_with_file):
        t = transfer_with_file
        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{uuid.uuid4()}/download/"
        )
        assert response.status_code == 404

    def test_download_from_expired(self, api_client):
        t = TransferFactory(expires_at=timezone.now() - timedelta(hours=1))
        tf = TransferFileFactory(transfer=t)

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/"
        )
        assert response.status_code == 410
