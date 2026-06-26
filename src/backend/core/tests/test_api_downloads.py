"""Tests for the download API endpoints (no auth required, but recognised
when present so an authenticated owner doesn't pollute the activity log)."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

import pytest

from core.enums import TransferEventType, TransferStatus
from core.factories import TransferFactory, TransferFileFactory, UserFactory
from core.models import TransferEvent
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
        # The owner's identity email must never reach the public payload.
        assert "owner_email" not in response.data
        # Anonymous visitor → not the owner.
        assert response.data["is_owner"] is False

        assert_single_event(t.id, TransferEventType.LINK_OPENED)

    def test_is_owner_true_for_authenticated_owner(
        self, authenticated_client, transfer_with_file
    ):
        # is_owner is resolved server-side from the session (no owner email
        # leaks to the client); the transfer owner sees it set to True.
        t = transfer_with_file
        response = authenticated_client.get(f"{DOWNLOADS_URL}/{t.public_token}/")
        assert response.status_code == 200
        assert response.data["is_owner"] is True
        # Even for the owner, the raw email must not leak into the payload.
        assert "owner_email" not in response.data

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

    def test_owner_view_skips_link_opened_event(
        self, authenticated_client, transfer_with_file
    ):
        # The owner's own visits aren't recipient signal — should not pollute
        # the audit log.
        response = authenticated_client.get(
            f"{DOWNLOADS_URL}/{transfer_with_file.public_token}/"
        )
        assert response.status_code == 200
        assert (
            TransferEvent.objects.filter(transfer_id=transfer_with_file.id).count()
            == 0
        )

    def test_authenticated_non_owner_view_logs_link_opened_event(
        self, api_client, transfer_with_file
    ):
        # A registered user who isn't the owner is still a recipient — log it.
        api_client.force_authenticate(user=UserFactory())
        response = api_client.get(
            f"{DOWNLOADS_URL}/{transfer_with_file.public_token}/"
        )
        assert response.status_code == 200
        assert_single_event(transfer_with_file.id, TransferEventType.LINK_OPENED)


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

    @patch("core.api.viewsets.download.sign_download_url")
    def test_owner_download_skips_file_downloaded_event(
        self, mock_sign, authenticated_client, transfer_with_file
    ):
        mock_sign.return_value = "https://s3.example.com/signed-get-url"
        tf = transfer_with_file.files.first()

        response = authenticated_client.get(
            f"{DOWNLOADS_URL}/{transfer_with_file.public_token}/files/{tf.id}/download/"
        )
        assert response.status_code == 302
        # Owner self-download → no audit event.
        assert (
            TransferEvent.objects.filter(transfer_id=transfer_with_file.id).count()
            == 0
        )

    @patch("core.api.viewsets.download.sign_download_url")
    def test_authenticated_non_owner_download_logs_file_downloaded_event(
        self, mock_sign, api_client, transfer_with_file
    ):
        mock_sign.return_value = "https://s3.example.com/signed-get-url"
        tf = transfer_with_file.files.first()
        api_client.force_authenticate(user=UserFactory())

        response = api_client.get(
            f"{DOWNLOADS_URL}/{transfer_with_file.public_token}/files/{tf.id}/download/"
        )
        assert response.status_code == 302
        assert_single_event(transfer_with_file.id, TransferEventType.FILE_DOWNLOADED)

    @patch("core.api.viewsets.download.sign_download_url")
    def test_download_file_as_json(self, mock_sign, api_client, transfer_with_file):
        # ``?as=json`` returns the presigned URL as data instead of a 302.
        # The E2E Service Worker uses this to fetch S3 anonymously and
        # avoid cross-origin redirect quirks with credentials.
        t = transfer_with_file
        tf = t.files.first()
        mock_sign.return_value = "https://s3.example.com/signed-get-url"

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/?as=json"
        )
        assert response.status_code == 200
        assert response.data == {"url": "https://s3.example.com/signed-get-url"}
        # Same audit semantics as the 302 path — FILE_DOWNLOADED is
        # recorded as soon as the URL is handed out.
        assert_single_event(t.id, TransferEventType.FILE_DOWNLOADED)
