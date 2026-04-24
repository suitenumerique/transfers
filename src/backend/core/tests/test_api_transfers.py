"""Tests for the Transfer API endpoints (read-only surface + deactivate).

The Transfer model now only holds finalized transfers — every row here
came into existence through a draft finalize. The upload lifecycle
(add-file, sign-part, complete-upload, remove-file, abort, finalize)
lives on ``/api/v1.0/drafts/`` and is covered by ``test_api_drafts.py``.

This file covers the public Transfer surface: list, retrieve, deactivate,
events.
"""

from django.utils import timezone

import pytest

from core.enums import ActorType, TransferEventType, TransferStatus
from core.factories import TransferFactory, TransferFileFactory
from core.models import TransferEvent
from core.tests.conftest import assert_single_event

API_URL = "/api/v1.0/transfers/"


@pytest.mark.django_db
class TestTransferList:
    """GET /api/v1.0/transfers/ — paginated list of the caller's finalized
    transfers. Drafts are a separate table and do not appear here."""

    def test_unauthenticated(self, api_client):
        response = api_client.get(API_URL)
        assert response.status_code == 401

    def test_list_shows_user_transfers(self, authenticated_client, user):
        transfer = TransferFactory(owner=user)
        TransferFileFactory(transfer=transfer, upload_completed_at=timezone.now())
        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(transfer.id)

    def test_list_empty(self, authenticated_client):
        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 0

    def test_list_excludes_other_users(self, authenticated_client, user):
        # Mine.
        mine = TransferFactory(owner=user)
        TransferFileFactory(transfer=mine, upload_completed_at=timezone.now())
        # Another user's.
        TransferFactory()

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(mine.id)

    def test_list_annotations(self, authenticated_client, user):
        transfer = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=transfer, size=100, upload_completed_at=timezone.now()
        )
        TransferFileFactory(
            transfer=transfer, size=200, upload_completed_at=timezone.now()
        )
        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.LINK_OPENED,
            actor_type=ActorType.EXTERNAL,
        )

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        row = response.data["results"][0]
        assert row["file_count"] == 2
        assert row["total_size"] == 300
        assert row["consulted"] is True
        assert row["downloaded"] is False

    def test_list_annotations_downloaded_true(self, authenticated_client, user):
        transfer = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=transfer, size=100, upload_completed_at=timezone.now()
        )
        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.FILE_DOWNLOADED,
            actor_type=ActorType.EXTERNAL,
        )

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        row = response.data["results"][0]
        assert row["downloaded"] is True
        assert row["consulted"] is False

    def test_list_annotations_isolation_across_transfers(
        self, authenticated_client, user
    ):
        """Events on one transfer must not leak into another's annotations.

        Guards against a regression where the Exists() subqueries would be
        replaced by a JOIN on TransferEvent: every row of the same user would
        then incorrectly pick up consulted=True as soon as ANY of their
        transfers had been opened once.
        """
        transfer_a = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=transfer_a, size=100, upload_completed_at=timezone.now()
        )
        TransferEvent.objects.create(
            transfer_id=transfer_a.id,
            event_type=TransferEventType.LINK_OPENED,
            actor_type=ActorType.EXTERNAL,
        )
        TransferEvent.objects.create(
            transfer_id=transfer_a.id,
            event_type=TransferEventType.FILE_DOWNLOADED,
            actor_type=ActorType.EXTERNAL,
        )

        transfer_b = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=transfer_b, size=200, upload_completed_at=timezone.now()
        )

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 2

        rows_by_id = {row["id"]: row for row in response.data["results"]}
        row_a = rows_by_id[str(transfer_a.id)]
        row_b = rows_by_id[str(transfer_b.id)]

        assert row_a["consulted"] is True
        assert row_a["downloaded"] is True
        assert row_a["file_count"] == 1
        assert row_a["total_size"] == 100

        assert row_b["consulted"] is False
        assert row_b["downloaded"] is False
        assert row_b["file_count"] == 1
        assert row_b["total_size"] == 200

    def test_list_annotations_duplicate_events_do_not_inflate_counts(
        self, authenticated_client, user
    ):
        """Multiple events of the same type must not multiply file_count/total_size.

        Classic JOIN trap: if the annotations joined TransferEvent instead of
        using Exists() subqueries, N LINK_OPENED events would multiply every
        file-based aggregate by N. The Count() / Exists() combo is immune —
        this test pins that invariant.
        """
        transfer = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=transfer, size=100, upload_completed_at=timezone.now()
        )
        TransferFileFactory(
            transfer=transfer, size=200, upload_completed_at=timezone.now()
        )
        for _ in range(3):
            TransferEvent.objects.create(
                transfer_id=transfer.id,
                event_type=TransferEventType.LINK_OPENED,
                actor_type=ActorType.EXTERNAL,
            )
            TransferEvent.objects.create(
                transfer_id=transfer.id,
                event_type=TransferEventType.FILE_DOWNLOADED,
                actor_type=ActorType.EXTERNAL,
            )

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        row = response.data["results"][0]
        assert row["file_count"] == 2
        assert row["total_size"] == 300
        assert row["consulted"] is True
        assert row["downloaded"] is True

    def test_list_annotations_zero_files(self, authenticated_client, user):
        """Transfer with no files must render zeros, not None.

        Pins that ``Sum(..., default=0)`` is in place — without the default,
        SUM over an empty set returns NULL and IntegerField.to_representation
        would crash on the list response.
        """
        TransferFactory(owner=user)

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 1
        row = response.data["results"][0]
        assert row["file_count"] == 0
        assert row["total_size"] == 0
        assert row["consulted"] is False
        assert row["downloaded"] is False


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
class TestTransferDeactivate:
    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(f"{API_URL}{transfer.id}/deactivate/")
        assert response.status_code == 401

    def test_deactivate(self, patched_s3, authenticated_client, user):
        transfer = TransferFactory(owner=user)
        TransferFileFactory(transfer=transfer, upload_completed_at=timezone.now())
        response = authenticated_client.post(f"{API_URL}{transfer.id}/deactivate/")

        assert response.status_code == 200
        # Deactivate is deferred: status flips to pending_file_deletion, the
        # actual S3 teardown + final transition to DEACTIVATED happens in
        # the sweep task.
        assert response.data["status"] == "pending_file_deletion"
        assert response.data["pending_deletion_at"] is not None
        assert response.data["deactivated_at"] is None
        assert response.data["deactivation_reason"] == "manual"
        patched_s3.delete.assert_not_called()

        assert_single_event(
            transfer.id, TransferEventType.TRANSFER_DEACTIVATED_MANUALLY
        )

    def test_deactivate_already_deactivated(self, authenticated_client, transfer):
        transfer.status = TransferStatus.DEACTIVATED
        transfer.save(update_fields=["status"])

        response = authenticated_client.post(f"{API_URL}{transfer.id}/deactivate/")
        assert response.status_code == 400

    def test_deactivate_already_pending(self, authenticated_client, transfer):
        transfer.status = TransferStatus.PENDING_FILE_DELETION
        transfer.save(update_fields=["status"])

        response = authenticated_client.post(f"{API_URL}{transfer.id}/deactivate/")
        assert response.status_code == 400

    def test_deactivate_rejects_other_user(self, authenticated_client):
        other_transfer = TransferFactory()
        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/deactivate/"
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
        response = authenticated_client.get(f"{API_URL}{other_transfer.id}/events/")
        assert response.status_code == 404
