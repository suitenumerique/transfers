"""Tests for the Transfer API endpoints (authenticated agent).

These tests cover the multipart upload flow: initiate, sign-part,
complete-upload, abort-upload. S3 is mocked via unittest.mock — we don't hit
the real object storage.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

from core.enums import TransferEventType, TransferStatus
from core.factories import TransferFactory, TransferFileFactory
from core.models import Transfer, TransferEvent, TransferFile
from core.tests.conftest import assert_single_event

API_URL = "/api/v1.0/transfers/"


@pytest.fixture
def patched_s3():
    """Patch every s3 service helper used by TransferViewSet."""
    with (
        patch(
            "core.api.viewsets.transfer.s3.create_multipart_upload",
            return_value="FAKE-UPLOAD-ID",
        ) as create_mock,
        patch(
            "core.api.viewsets.transfer.s3.sign_upload_part",
            return_value="https://s3.example.com/part-url",
        ) as sign_mock,
        patch("core.api.viewsets.transfer.s3.complete_multipart_upload") as complete_mock,
        patch("core.api.viewsets.transfer.s3.abort_multipart_upload") as abort_mock,
        patch("core.api.viewsets.transfer.s3.delete_object") as delete_mock,
    ):
        yield MagicMock(
            create=create_mock,
            sign=sign_mock,
            complete=complete_mock,
            abort=abort_mock,
            delete=delete_mock,
        )


@pytest.mark.django_db
class TestTransferList:
    def test_unauthenticated(self, api_client):
        response = api_client.get(API_URL)
        assert response.status_code == 401

    def test_list_shows_only_completed_uploads(self, authenticated_client, user):
        completed = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=completed, upload_completed_at=timezone.now()
        )
        pending = TransferFactory(owner=user)  # noqa: F841
        TransferFileFactory(transfer=pending, upload_completed_at=None)

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(completed.id)

    def test_list_empty(self, authenticated_client):
        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 0


@pytest.mark.django_db
class TestTransferDetail:
    def test_unauthenticated(self, api_client, transfer):
        response = api_client.get(f"{API_URL}{transfer.id}/")
        assert response.status_code == 401

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
class TestTransferInitiate:
    """Covers POST /transfers/ — initiates a multipart upload."""

    def test_unauthenticated(self, api_client):
        response = api_client.post(
            API_URL, {"filename": "a.bin", "size": 100}, format="json"
        )
        assert response.status_code == 401

    def test_initiate_creates_transfer_and_file(
        self, patched_s3, authenticated_client, user
    ):
        response = authenticated_client.post(
            API_URL,
            {
                "title": "My transfer",
                "expires_in_days": 30,
                "filename": "report.pdf",
                "size": 25 * 1024 * 1024,  # 25 MiB
                "mime_type": "application/pdf",
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["upload_id"] == "FAKE-UPLOAD-ID"
        assert response.data["chunk_size"] > 0
        assert "transfer_id" in response.data
        assert "transfer_file_id" in response.data
        assert "public_token" in response.data

        transfer = Transfer.objects.get(id=response.data["transfer_id"])
        assert transfer.owner == user
        assert transfer.title == "My transfer"
        assert transfer.status == TransferStatus.ACTIVE

        tf = transfer.files.get()
        assert tf.filename == "report.pdf"
        assert tf.size == 25 * 1024 * 1024
        assert tf.mime_type == "application/pdf"
        assert tf.upload_id == "FAKE-UPLOAD-ID"
        assert tf.upload_completed_at is None
        assert tf.s3_key.startswith(f"transfers/{transfer.id}/")

        patched_s3.create.assert_called_once()

    def test_initiate_default_expiry(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            API_URL,
            {"filename": "a.bin", "size": 100},
            format="json",
        )
        assert response.status_code == 201
        transfer = Transfer.objects.get(id=response.data["transfer_id"])
        delta = (transfer.expires_at - transfer.created_at).total_seconds()
        assert delta == pytest.approx(30 * 86400, abs=1)

    def test_initiate_invalid_expiry(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            API_URL,
            {"filename": "a.bin", "size": 100, "expires_in_days": 999},
            format="json",
        )
        assert response.status_code == 400

    def test_initiate_file_too_large(
        self, patched_s3, authenticated_client, settings
    ):
        response = authenticated_client.post(
            API_URL,
            {
                "filename": "huge.bin",
                "size": settings.TRANSFER_MAX_FILE_SIZE + 1,
            },
            format="json",
        )
        assert response.status_code == 400

    def test_initiate_missing_filename(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            API_URL, {"size": 100}, format="json"
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestTransferSignPart:
    """Covers POST /transfers/{id}/sign-part/."""

    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(
            f"{API_URL}{transfer.id}/sign-part/",
            {"transfer_file_id": str(transfer.id), "part_number": 1},
            format="json",
        )
        assert response.status_code == 401

    def _initiate(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            API_URL,
            {"filename": "a.bin", "size": 50 * 1024 * 1024},
            format="json",
        )
        return response.data

    def test_sign_part_returns_url(self, patched_s3, authenticated_client):
        initiate = self._initiate(patched_s3, authenticated_client)
        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/sign-part/",
            {
                "transfer_file_id": initiate["transfer_file_id"],
                "part_number": 1,
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.data["url"] == "https://s3.example.com/part-url"
        assert response.data["part_number"] == 1
        patched_s3.sign.assert_called_once()

    def test_sign_part_rejects_other_user(self, patched_s3, authenticated_client):
        other_transfer = TransferFactory()
        tf = TransferFileFactory(transfer=other_transfer, upload_id="UPID")

        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/sign-part/",
            {"transfer_file_id": str(tf.id), "part_number": 1},
            format="json",
        )
        assert response.status_code == 404  # filtered by owner queryset

    def test_sign_part_after_completion_rejected(
        self, patched_s3, authenticated_client, user
    ):
        transfer = TransferFactory(owner=user)
        tf = TransferFileFactory(
            transfer=transfer,
            upload_id="",
            upload_completed_at=timezone.now(),
        )
        response = authenticated_client.post(
            f"{API_URL}{transfer.id}/sign-part/",
            {"transfer_file_id": str(tf.id), "part_number": 1},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestTransferCompleteUpload:
    """Covers POST /transfers/{id}/complete-upload/."""

    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(
            f"{API_URL}{transfer.id}/complete-upload/",
            {
                "transfer_file_id": str(transfer.id),
                "parts": [{"PartNumber": 1, "ETag": '"e"'}],
            },
            format="json",
        )
        assert response.status_code == 401

    def _initiate(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            API_URL,
            {"filename": "a.bin", "size": 100},
            format="json",
        )
        return response.data

    def test_complete_marks_file_and_emits_event(
        self, patched_s3, authenticated_client
    ):
        initiate = self._initiate(patched_s3, authenticated_client)
        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/complete-upload/",
            {
                "transfer_file_id": initiate["transfer_file_id"],
                "parts": [
                    {"PartNumber": 1, "ETag": '"etag-1"'},
                ],
            },
            format="json",
        )
        assert response.status_code == 200, response.data
        patched_s3.complete.assert_called_once()

        tf = TransferFile.objects.get(id=initiate["transfer_file_id"])
        assert tf.upload_completed_at is not None
        assert tf.upload_id == ""

        assert_single_event(
            initiate["transfer_id"], TransferEventType.TRANSFER_CREATED
        )

    def test_complete_with_empty_parts_rejected(
        self, patched_s3, authenticated_client
    ):
        initiate = self._initiate(patched_s3, authenticated_client)
        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/complete-upload/",
            {
                "transfer_file_id": initiate["transfer_file_id"],
                "parts": [],
            },
            format="json",
        )
        assert response.status_code == 400
        patched_s3.complete.assert_not_called()

    def test_complete_twice_rejected(self, patched_s3, authenticated_client):
        initiate = self._initiate(patched_s3, authenticated_client)
        body = {
            "transfer_file_id": initiate["transfer_file_id"],
            "parts": [{"PartNumber": 1, "ETag": '"etag-1"'}],
        }
        authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/complete-upload/",
            body,
            format="json",
        )
        # Second call should fail because upload is already complete.
        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/complete-upload/",
            body,
            format="json",
        )
        assert response.status_code == 400

    def test_complete_rejects_other_user(self, patched_s3, authenticated_client):
        other_transfer = TransferFactory()
        tf = TransferFileFactory(transfer=other_transfer, upload_id="UPID")

        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/complete-upload/",
            {
                "transfer_file_id": str(tf.id),
                "parts": [{"PartNumber": 1, "ETag": '"e"'}],
            },
            format="json",
        )
        assert response.status_code == 404

    def test_complete_cleans_up_on_s3_error(
        self, patched_s3, authenticated_client
    ):
        # Make S3.complete_multipart_upload raise a ClientError — simulates a
        # bogus ETag or corrupted parts list.
        from botocore.exceptions import ClientError

        patched_s3.complete.side_effect = ClientError(
            {"Error": {"Code": "InvalidPart", "Message": "One or more of the specified parts could not be found"}},
            "CompleteMultipartUpload",
        )

        initiate = self._initiate(patched_s3, authenticated_client)
        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/complete-upload/",
            {
                "transfer_file_id": initiate["transfer_file_id"],
                "parts": [{"PartNumber": 1, "ETag": '"bogus"'}],
            },
            format="json",
        )

        # Client gets a 400 with a useful message.
        assert response.status_code == 400
        assert "parts" in response.data
        assert "InvalidPart" in str(response.data["parts"])

        # Cleanup: abort_multipart_upload was called, rows deleted.
        patched_s3.abort.assert_called_once()
        assert not Transfer.objects.filter(id=initiate["transfer_id"]).exists()
        assert not TransferFile.objects.filter(
            id=initiate["transfer_file_id"]
        ).exists()


@pytest.mark.django_db
class TestTransferAbortUpload:
    """Covers POST /transfers/{id}/abort-upload/."""

    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(
            f"{API_URL}{transfer.id}/abort-upload/",
            {"transfer_file_id": str(transfer.id)},
            format="json",
        )
        assert response.status_code == 401

    def test_abort_deletes_rows_and_calls_s3(
        self, patched_s3, authenticated_client
    ):
        initiate_resp = authenticated_client.post(
            API_URL,
            {"filename": "a.bin", "size": 100},
            format="json",
        )
        initiate = initiate_resp.data

        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/abort-upload/",
            {"transfer_file_id": initiate["transfer_file_id"]},
            format="json",
        )
        assert response.status_code == 204
        patched_s3.abort.assert_called_once()

        assert not Transfer.objects.filter(id=initiate["transfer_id"]).exists()
        assert not TransferFile.objects.filter(
            id=initiate["transfer_file_id"]
        ).exists()

    def test_abort_rejects_other_user(self, patched_s3, authenticated_client):
        other_transfer = TransferFactory()
        tf = TransferFileFactory(transfer=other_transfer, upload_id="UPID")

        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/abort-upload/",
            {"transfer_file_id": str(tf.id)},
            format="json",
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestTransferRevoke:
    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(f"{API_URL}{transfer.id}/revoke/")
        assert response.status_code == 401

    def test_revoke(self, patched_s3, authenticated_client, user):
        transfer = TransferFactory(owner=user)
        TransferFileFactory(transfer=transfer, upload_completed_at=timezone.now())
        response = authenticated_client.post(f"{API_URL}{transfer.id}/revoke/")

        assert response.status_code == 200
        assert response.data["status"] == "revoked"
        assert response.data["revoked_at"] is not None
        patched_s3.delete.assert_called()

        assert_single_event(transfer.id, TransferEventType.TRANSFER_REVOKED)

    def test_revoke_already_revoked(self, authenticated_client, transfer):
        transfer.status = TransferStatus.REVOKED
        transfer.save(update_fields=["status"])

        response = authenticated_client.post(f"{API_URL}{transfer.id}/revoke/")
        assert response.status_code == 400

    def test_revoke_rejects_other_user(self, authenticated_client):
        other_transfer = TransferFactory()
        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/revoke/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestTransferReactivate:
    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(f"{API_URL}{transfer.id}/reactivate/")
        assert response.status_code == 401

    def test_reactivate_expired(self, authenticated_client, transfer):
        transfer.status = TransferStatus.EXPIRED
        transfer.expires_at = timezone.now() - timedelta(hours=1)
        transfer.save(update_fields=["status", "expires_at"])
        old_token = transfer.public_token

        response = authenticated_client.post(
            f"{API_URL}{transfer.id}/reactivate/"
        )

        assert response.status_code == 200
        assert response.data["status"] == "active"
        assert response.data["public_token"] == old_token

    def test_reactivate_active_fails(self, authenticated_client, transfer):
        response = authenticated_client.post(
            f"{API_URL}{transfer.id}/reactivate/"
        )
        assert response.status_code == 400

    def test_reactivate_after_files_deleted_fails(
        self, authenticated_client, transfer
    ):
        # Expired AND files have been purged past the grace period.
        transfer.status = TransferStatus.EXPIRED
        transfer.expires_at = timezone.now() - timedelta(days=10)
        transfer.files_deleted_at = timezone.now() - timedelta(days=3)
        transfer.save(
            update_fields=["status", "expires_at", "files_deleted_at"]
        )

        response = authenticated_client.post(
            f"{API_URL}{transfer.id}/reactivate/"
        )
        assert response.status_code == 400
        # Nothing should have been touched.
        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.EXPIRED
        assert transfer.files_deleted_at is not None

    def test_reactivate_rejects_other_user(self, authenticated_client):
        other_transfer = TransferFactory(status=TransferStatus.EXPIRED)
        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/reactivate/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestTransferEvents:
    def test_unauthenticated(self, api_client, transfer):
        response = api_client.get(f"{API_URL}{transfer.id}/events/")
        assert response.status_code == 401

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

    def test_events_rejects_other_user(self, authenticated_client):
        other_transfer = TransferFactory()
        response = authenticated_client.get(
            f"{API_URL}{other_transfer.id}/events/"
        )
        assert response.status_code == 404
