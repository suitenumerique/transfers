"""Tests for the download API endpoints (no auth required, but recognised
when present so an authenticated owner doesn't pollute the activity log)."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

import pytest

from core.enums import ScanStatus, TransferEventType, TransferStatus
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
        # The owner's own visits are never journaled, so the download page
        # needs this flag to say that no receipt will follow.
        assert response.data["notify_on_download"] is False

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
            TransferEvent.objects.filter(transfer_id=transfer_with_file.id).count() == 0
        )

    def test_authenticated_non_owner_view_logs_link_opened_event(
        self, api_client, transfer_with_file
    ):
        # A registered user who isn't the owner is still a recipient — log it.
        api_client.force_authenticate(user=UserFactory())
        response = api_client.get(f"{DOWNLOADS_URL}/{transfer_with_file.public_token}/")
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
            TransferEvent.objects.filter(transfer_id=transfer_with_file.id).count() == 0
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
        # The encryption Service Worker uses this to fetch S3 anonymously and
        # avoid cross-origin redirect quirks with credentials.
        t = transfer_with_file
        tf = t.files.first()
        mock_sign.return_value = "https://s3.example.com/signed-get-url"

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{tf.id}/download/?as=json"
        )
        assert response.status_code == 200
        assert response.data == {"url": "https://s3.example.com/signed-get-url"}
        # The presigned URL is short-lived and single-recipient — it must never
        # be cached by a proxy or the browser.
        assert response["Cache-Control"] == "no-store"
        # Same audit semantics as the 302 path — FILE_DOWNLOADED is
        # recorded as soon as the URL is handed out.
        assert_single_event(t.id, TransferEventType.FILE_DOWNLOADED)


@pytest.mark.django_db
class TestRecipientAttribution:
    """``?r=<recipient token>`` on the emailed link is what turns anonymous
    visitor events into per-recipient activity."""

    def _recipient(self, transfer, email="dest@example.org"):
        return transfer.recipients.create(email=email, email_sent_at=timezone.now())

    def test_link_opened_is_attributed_to_the_recipient(
        self, api_client, transfer_with_file
    ):
        t = transfer_with_file
        recipient = self._recipient(t)

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/?r={recipient.token}"
        )

        assert response.status_code == 200
        event = TransferEvent.objects.get(
            transfer_id=t.id, event_type=TransferEventType.LINK_OPENED
        )
        assert event.recipient_id == recipient.id

    def test_bare_or_foreign_token_stays_anonymous(
        self, api_client, transfer_with_file
    ):
        """A copied link (no token), a token from another transfer, or a
        made-up one must neither error nor be attributed."""
        t = transfer_with_file
        other = TransferFactory()
        foreign = other.recipients.create(email="x@example.org")

        for query in ("", f"?r={foreign.token}", "?r=nope"):
            response = api_client.get(f"{DOWNLOADS_URL}/{t.public_token}/{query}")
            assert response.status_code == 200

        events = TransferEvent.objects.filter(
            transfer_id=t.id, event_type=TransferEventType.LINK_OPENED
        )
        assert events.count() == 3
        assert all(e.recipient_id is None for e in events)

    @patch("core.api.viewsets.download.sign_download_url", return_value="https://s3/x")
    def test_file_downloaded_is_attributed(self, _sign, api_client, transfer_with_file):
        t = transfer_with_file
        recipient = self._recipient(t)
        file_id = t.files.first().id

        response = api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{file_id}/download/?r={recipient.token}"
        )

        assert response.status_code == 302
        event = TransferEvent.objects.get(
            transfer_id=t.id, event_type=TransferEventType.FILE_DOWNLOADED
        )
        assert event.recipient_id == recipient.id

    @patch("core.api.viewsets.download.sign_download_url", return_value="https://s3/x")
    @patch("core.tasks.send_download_receipt_task.apply_async")
    @patch("core.tasks.send_download_receipt_task.delay")
    def test_receipt_queued_once_every_file_is_downloaded(
        self,
        delay,
        apply_async,
        _sign,
        api_client,
        transfer_with_file,
        django_capture_on_commit_callbacks,
        settings,
    ):
        """Opt-in transfer, two files. The first attributed download arms
        the delayed "partial" receipt once (persisted claim); the download
        that completes the set sends immediately; a bare link never
        triggers anything."""
        settings.TRANSFER_DOWNLOAD_RECEIPT_DELAY = 1234
        t = transfer_with_file
        t.notify_on_download = True
        t.save(update_fields=["notify_on_download"])
        second = TransferFileFactory(
            transfer=t,
            upload_completed_at=timezone.now(),
            scan_status=ScanStatus.CLEAN,  # the factory default is PENDING → 202
        )
        first = t.files.exclude(id=second.id).get()
        recipient = self._recipient(t)
        base = f"{DOWNLOADS_URL}/{t.public_token}/files"

        # The receipt is enqueued on commit; the test transaction never
        # commits, so run the captured callbacks explicitly.
        def get(path):
            with django_capture_on_commit_callbacks(execute=True):
                return api_client.get(path)

        # Anonymous download of the first file: nothing attributed, no receipt.
        get(f"{base}/{first.id}/download/")
        assert delay.call_count == 0
        assert apply_async.call_count == 0

        # First attributed download: one of two files → arm the delayed
        # partial receipt with the configured countdown, nothing immediate.
        get(f"{base}/{first.id}/download/?r={recipient.token}")
        assert delay.call_count == 0
        apply_async.assert_called_once_with(
            args=(str(t.id), str(recipient.id)), countdown=1234
        )

        recipient.refresh_from_db()
        assert recipient.delayed_receipt_armed_at is not None

        # Any further incomplete download finds the claim taken: no second
        # timer, whether it's the same file again or another one.
        get(f"{base}/{first.id}/download/?r={recipient.token}")
        assert apply_async.call_count == 1

        get(f"{base}/{second.id}/download/?r={recipient.token}")
        delay.assert_called_once_with(str(t.id), str(recipient.id))
        assert apply_async.call_count == 1

        # Re-downloading after the receipt was stamped must not re-queue.
        recipient.download_notified_at = timezone.now()
        recipient.save(update_fields=["download_notified_at"])
        get(f"{base}/{second.id}/download/?r={recipient.token}")
        assert delay.call_count == 1

    @patch("core.api.viewsets.download.sign_download_url", return_value="https://s3/x")
    @patch("core.tasks.send_download_receipt_task.delay")
    def test_receipt_not_queued_without_opt_in(
        self, delay, _sign, api_client, transfer_with_file
    ):
        t = transfer_with_file
        recipient = self._recipient(t)
        file_id = t.files.first().id

        api_client.get(
            f"{DOWNLOADS_URL}/{t.public_token}/files/{file_id}/download/?r={recipient.token}"
        )

        assert delay.call_count == 0
