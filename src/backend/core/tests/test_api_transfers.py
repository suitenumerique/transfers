"""Tests for the Transfer API endpoints (read-only surface + deactivate).

The Transfer model now only holds finalized transfers — every row here
came into existence through a draft finalize. The upload lifecycle
(add-file, sign-part, complete-upload, remove-file, abort, finalize)
lives on ``/api/v1.0/drafts/`` and is covered by ``test_api_drafts.py``.

This file covers the public Transfer surface: list, retrieve, deactivate,
events.
"""

from datetime import timedelta

from django.conf import settings
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

    def test_list_deactivated_false_returns_only_active(
        self, authenticated_client, user
    ):
        active = TransferFactory(owner=user, status=TransferStatus.ACTIVE)
        TransferFactory(owner=user, status=TransferStatus.PENDING_FILE_DELETION)
        TransferFactory(owner=user, status=TransferStatus.DEACTIVATED)

        response = authenticated_client.get(f"{API_URL}?deactivated=false")
        assert response.status_code == 200
        ids = {row["id"] for row in response.data["results"]}
        assert ids == {str(active.id)}

    def test_list_deactivated_true_returns_non_active(self, authenticated_client, user):
        TransferFactory(owner=user, status=TransferStatus.ACTIVE)
        pending = TransferFactory(
            owner=user, status=TransferStatus.PENDING_FILE_DELETION
        )
        deactivated = TransferFactory(owner=user, status=TransferStatus.DEACTIVATED)

        response = authenticated_client.get(f"{API_URL}?deactivated=true")
        assert response.status_code == 200
        ids = {row["id"] for row in response.data["results"]}
        assert ids == {str(pending.id), str(deactivated.id)}

    def test_list_search_matches_title_case_insensitive(
        self, authenticated_client, user
    ):
        match_lower = TransferFactory(owner=user, title="quarterly report q4")
        match_upper = TransferFactory(owner=user, title="MY QUARTERLY BUDGET")
        TransferFactory(owner=user, title="something else entirely")

        response = authenticated_client.get(f"{API_URL}?search=quarterly")
        assert response.status_code == 200
        ids = {row["id"] for row in response.data["results"]}
        assert ids == {str(match_lower.id), str(match_upper.id)}


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

        transfer.refresh_from_db()
        assert transfer.status == "pending_file_deletion"
        assert transfer.deactivation_reason == "manual"
        expected_deletion = timezone.now() + timedelta(
            hours=settings.TRANSFER_PURGE_DELAY_HOURS
        )
        assert (
            abs((transfer.pending_deletion_at - expected_deletion).total_seconds()) < 5
        )

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
class TestTransferHardDelete:
    """DELETE /api/v1.0/transfers/<id>/ — hard-delete a fully-deactivated
    transfer (row + FK-cascaded files + recipients). ``TransferEvent`` is
    deliberately not FK-linked so its audit trail survives. Guarded by
    ``status == DEACTIVATED`` so we never orphan S3 bytes."""

    def _deactivated(self, owner):
        """Build a Transfer + one file + one recipient + a couple of events
        already in the terminal DEACTIVATED state — the state the hard-
        delete is designed for."""
        transfer = TransferFactory(owner=owner, status=TransferStatus.DEACTIVATED)
        TransferFileFactory(transfer=transfer, upload_completed_at=timezone.now())
        transfer.recipients.create(email="r@example.org")
        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_CREATED,
            actor_type=ActorType.AGENT,
        )
        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_DEACTIVATED_MANUALLY,
            actor_type=ActorType.AGENT,
        )
        return transfer

    def test_unauthenticated(self, api_client, transfer):
        response = api_client.delete(f"{API_URL}{transfer.id}/")
        assert response.status_code == 401

    def test_purges_transfer_and_fk_children_but_keeps_events(
        self, authenticated_client, user
    ):
        """Nominal path: the DEACTIVATED transfer row + FK-cascaded files +
        recipients are gone; the events survive because ``transfer_id`` is
        a plain UUIDField (not a FK), matching the class docstring's
        "survive Transfer deletion" contract.
        """
        from core.models import Transfer, TransferFile, TransferRecipient

        transfer = self._deactivated(user)
        pre_event_ids = list(
            TransferEvent.objects.filter(transfer_id=transfer.id).values_list(
                "id", flat=True
            )
        )
        assert len(pre_event_ids) == 2  # sanity: fixture created two events

        response = authenticated_client.delete(f"{API_URL}{transfer.id}/")

        assert response.status_code == 204
        assert not Transfer.objects.filter(id=transfer.id).exists()
        # FK cascade for files + recipients:
        assert not TransferFile.objects.filter(transfer_id=transfer.id).exists()
        assert not TransferRecipient.objects.filter(transfer_id=transfer.id).exists()
        # Events stay behind, un-touched, on the audit trail.
        assert TransferEvent.objects.filter(id__in=pre_event_ids).count() == len(
            pre_event_ids
        )

    def test_refuses_active_transfer(self, authenticated_client, user):
        """The link is still live — killing it silently would surprise the
        recipient. The agent must deactivate first, then delete. Backend
        guard is defense-in-depth; the frontend hides the button too."""
        from core.models import Transfer

        transfer = TransferFactory(owner=user, status=TransferStatus.ACTIVE)
        TransferFileFactory(
            transfer=transfer,
            upload_completed_at=timezone.now(),
            s3_key="transfers/x/live.bin",
        )

        response = authenticated_client.delete(f"{API_URL}{transfer.id}/")

        assert response.status_code == 400
        assert "status" in response.data
        # Row must be intact.
        assert Transfer.objects.filter(id=transfer.id).exists()

    def test_wipes_s3_then_purges_pending_file_deletion(
        self, patched_s3, authenticated_client, user
    ):
        """PENDING_FILE_DELETION also still owns S3 objects (waiting for the
        grace window to elapse before the periodic sweep purges them).
        Hard-delete bypasses the grace and wipes immediately."""
        from core.models import Transfer

        transfer = TransferFactory(
            owner=user, status=TransferStatus.PENDING_FILE_DELETION
        )
        f = TransferFileFactory(
            transfer=transfer,
            upload_completed_at=timezone.now(),
            s3_key="transfers/y/pending.bin",
        )

        response = authenticated_client.delete(f"{API_URL}{transfer.id}/")

        assert response.status_code == 204
        patched_s3.delete.assert_any_call(f.s3_key)
        assert not Transfer.objects.filter(id=transfer.id).exists()

    def test_refuses_when_s3_delete_fails(self, patched_s3, authenticated_client, user):
        """S3 hiccup on wipe → 400, row + files intact. Otherwise deleting
        the row would strand S3 objects the periodic sweep can no longer
        find via a ``TransferFile.s3_key`` lookup."""
        from botocore.exceptions import ClientError

        from core.models import Transfer, TransferFile

        # PENDING_FILE_DELETION still owns S3 bytes, so the wipe runs.
        transfer = TransferFactory(
            owner=user, status=TransferStatus.PENDING_FILE_DELETION
        )
        TransferFileFactory(
            transfer=transfer,
            upload_completed_at=timezone.now(),
            s3_key="transfers/z/hiccup.bin",
        )
        # Make delete_object raise a ClientError; the best-effort helper
        # swallows it and returns False.
        patched_s3.delete.side_effect = ClientError(
            {"Error": {"Code": "InternalError"}}, "DeleteObject"
        )

        response = authenticated_client.delete(f"{API_URL}{transfer.id}/")

        assert response.status_code == 400
        # Pin the exact user-facing copy — PENDING_FILE_DELETION is
        # invisible in the UI ("Deactivated" badge), so this branch has
        # to (a) return the generic retryable message the modal shows
        # and (b) never leak an internal term. A "detail" key alone
        # would let a regression to "Some files could not be deleted
        # from storage." pass silently — that copy still fits the shape
        # but contradicts the deactivate confirm's "files will be
        # deleted" promise.
        expected = "This transfer can't be deleted right now. Try again in a moment."
        detail = response.data["detail"]
        assert (detail[0] if isinstance(detail, list) else detail) == expected
        body = str(response.data).lower()
        for banned in ("storage", "s3", "pending_file_deletion"):
            assert banned not in body, (
                f"Response leaks internal term {banned!r}: {response.data!r}"
            )
        assert Transfer.objects.filter(id=transfer.id).exists()
        assert TransferFile.objects.filter(transfer_id=transfer.id).exists()

    def test_rejects_other_user(self, authenticated_client):
        """A non-owner sees the same 404 as if the row didn't exist — the
        owner filter lives in ``get_queryset`` and gates every action."""
        other_transfer = TransferFactory(status=TransferStatus.DEACTIVATED)
        response = authenticated_client.delete(f"{API_URL}{other_transfer.id}/")
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


@pytest.mark.django_db
class TestRecipientStatuses:
    """The detail payload folds the event log into one status per recipient
    — what the recipients list on the summary and detail pages renders."""

    def _detail(self, client, transfer):
        response = client.get(f"{API_URL}{transfer.id}/")
        assert response.status_code == 200
        return {r["email"]: r for r in response.data["recipients"]}

    def _setup(self, user, *, sent, events=()):
        """One two-file transfer, one recipient, the given attributed events
        ("open", "f1", "f2"). Status derivation reads the event log only;
        scan state is irrelevant here."""
        transfer = TransferFactory(owner=user, sharing_mode="email")
        files = {
            "f1": TransferFileFactory(
                transfer=transfer, upload_completed_at=timezone.now()
            ),
            "f2": TransferFileFactory(
                transfer=transfer, upload_completed_at=timezone.now()
            ),
        }
        recipient = transfer.recipients.create(
            email="dest@example.org",
            email_sent_at=timezone.now() if sent else None,
        )
        for token in events:
            TransferEvent.objects.create(
                transfer_id=transfer.id,
                recipient_id=recipient.id,
                event_type=(
                    TransferEventType.LINK_OPENED
                    if token == "open"
                    else TransferEventType.FILE_DOWNLOADED
                ),
                actor_type=ActorType.EXTERNAL,
                payload={} if token == "open" else {"file_id": str(files[token].id)},
            )
        return transfer, recipient

    @pytest.mark.parametrize(
        ("sent", "events", "expected"),
        [
            # Invitation task still running, nothing sent yet.
            (False, [], {"status": "sending"}),
            (True, [], {"status": "sent", "downloaded_file_count": 0}),
            (True, ["open"], {"status": "opened", "opened_at": "set"}),
            (
                True,
                ["open", "f1"],
                {"status": "downloaded", "downloaded_file_count": 1},
            ),
            # Re-downloading f2 counts once.
            (
                True,
                ["open", "f1", "f2", "f2"],
                {
                    "status": "downloaded",
                    "downloaded_file_count": 2,
                    "downloaded_at": "set",
                },
            ),
        ],
        ids=["sending", "sent", "opened", "partial", "complete"],
    )
    def test_status_follows_delivery_and_activity(
        self, authenticated_client, user, sent, events, expected
    ):
        transfer, _ = self._setup(user, sent=sent, events=events)

        row = self._detail(authenticated_client, transfer)["dest@example.org"]

        for key, value in expected.items():
            if value == "set":
                assert row[key] is not None, key
            else:
                assert row[key] == value, key

    def test_unsent_becomes_failed_once_the_invitation_task_completed(
        self, authenticated_client, user
    ):
        transfer, recipient = self._setup(user, sent=False)
        transfer.notifications_completed_at = timezone.now()
        transfer.save(update_fields=["notifications_completed_at"])

        row = self._detail(authenticated_client, transfer)["dest@example.org"]

        assert row["status"] == "failed"
        assert recipient.email_sent_at is None

    def test_anonymous_download_is_not_attributed(self, authenticated_client, user):
        """A download through a bare link (no ``?r=``) carries no recipient
        and must not move anyone's status."""
        transfer, _ = self._setup(user, sent=True)
        TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.FILE_DOWNLOADED,
            actor_type=ActorType.EXTERNAL,
            payload={"file_id": str(transfer.files.first().id)},
        )

        row = self._detail(authenticated_client, transfer)["dest@example.org"]

        assert row["status"] == "sent"
        assert row["downloaded_file_count"] == 0

    def test_detail_recipients_cost_a_bounded_number_of_queries(
        self, authenticated_client, user, django_assert_max_num_queries
    ):
        """Activity is folded in one query for the whole transfer — the
        recipients list must not fan out per row."""
        transfer = TransferFactory(owner=user, sharing_mode="email")
        TransferFileFactory(transfer=transfer, upload_completed_at=timezone.now())
        for i in range(20):
            transfer.recipients.create(
                email=f"r{i}@example.org", email_sent_at=timezone.now()
            )

        with django_assert_max_num_queries(12):
            response = authenticated_client.get(f"{API_URL}{transfer.id}/")
        assert response.status_code == 200
        assert len(response.data["recipients"]) == 20
