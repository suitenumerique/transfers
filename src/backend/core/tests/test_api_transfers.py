"""Tests for the Transfer API endpoints (authenticated agent).

These tests cover the draft + multipart upload flow: add-file (which also
opens the draft on the first call), sign-part, complete-upload, remove-file,
abort-upload, and finalize (where transfer-level metadata is applied in one
shot). S3 is mocked via unittest.mock — we don't hit the real object storage.
"""

from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

from core.enums import ActorType, TransferEventType, TransferStatus
from core.factories import TransferFactory, TransferFileFactory
from core.models import Transfer, TransferEvent, TransferFile
from core.tests.conftest import assert_single_event

API_URL = "/api/v1.0/transfers/"


@pytest.fixture
def patched_s3():
    """Patch every s3 service helper used by TransferViewSet.

    ``head_object_size`` returns whatever ``transfer_file.size`` says by
    default — tests that want to simulate a size mismatch override the
    ``head.return_value`` or ``head.side_effect``.
    """
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
        patch(
            "core.api.viewsets.transfer.s3.head_object_size",
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


def _head_matching_declared_size(key):
    """Default head_object_size stub: look up the TransferFile by s3_key and
    return whatever size it was created with. This makes the size check pass
    for happy-path tests; tests simulating a mismatch override the mock."""
    from core.models import TransferFile

    return TransferFile.objects.get(s3_key=key).size


@pytest.mark.django_db
class TestTransferList:
    def test_unauthenticated(self, api_client):
        response = api_client.get(API_URL)
        assert response.status_code == 401

    def test_list_shows_only_finalized_transfers(self, authenticated_client, user):
        # Finalized: factory sets upload_completed_at + public_token by default.
        finalized = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=finalized, upload_completed_at=timezone.now()
        )
        # Pending: explicitly clear the finalization markers on the transfer.
        pending = TransferFactory(
            owner=user,
            public_token=None,
            upload_completed_at=None,
        )
        TransferFileFactory(transfer=pending, upload_completed_at=None)

        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(finalized.id)

    def test_list_empty(self, authenticated_client):
        response = authenticated_client.get(API_URL)
        assert response.status_code == 200
        assert response.data["count"] == 0

    def test_list_annotations(self, authenticated_client, user):
        transfer = TransferFactory(owner=user)
        TransferFileFactory(
            transfer=transfer, size=100, upload_completed_at=timezone.now()
        )
        TransferFileFactory(
            transfer=transfer, size=200, upload_completed_at=timezone.now()
        )
        # One pending file must NOT be counted in file_count / total_size.
        TransferFileFactory(transfer=transfer, size=999, upload_completed_at=None)
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
        # No LINK_OPENED event recorded → consulted stays False.
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

        # Transfer B is untouched — no LINK_OPENED, no FILE_DOWNLOADED.
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
        file-based aggregate by N. The Count(..., filter=...) / Exists()
        combo is immune — this test pins that invariant.
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

    def test_list_annotations_zero_completed_files(
        self, authenticated_client, user
    ):
        """A finalized transfer with no completed files must render 0, not None.

        Pins that ``Sum(..., default=0)`` is in place — without the default,
        SUM over an empty set returns NULL and IntegerField.to_representation
        would crash on the list response.
        """
        TransferFactory(owner=user)  # no TransferFileFactory calls

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


ADD_FILE_URL = f"{API_URL}add-file/"


def _add_file(authenticated_client, transfer_id=None, **file_body):
    """Helper: POST /transfers/add-file/. Omit ``transfer_id`` for the first
    drop (which opens the draft as a side-effect); pass it on subsequent
    drops to attach the file to the same draft."""
    defaults = {"filename": "a.bin", "size": 100}
    defaults.update(file_body)
    body = dict(defaults)
    if transfer_id is not None:
        body["transfer_id"] = str(transfer_id)
    return authenticated_client.post(ADD_FILE_URL, body, format="json")


def _initiate_with_file(authenticated_client, **file_body):
    """First-drop helper: opens a draft and attaches one file. Returns the
    response fields the downstream tests (sign-part, complete-upload,
    finalize) need to wire their calls."""
    resp = _add_file(authenticated_client, **file_body)
    assert resp.status_code == 201, resp.data
    return {
        "transfer_id": resp.data["transfer_id"],
        "transfer_file_id": resp.data["transfer_file_id"],
        "upload_id": resp.data["upload_id"],
        "s3_key": resp.data["s3_key"],
        "chunk_size": resp.data["chunk_size"],
    }


def _complete_upload(authenticated_client, transfer_id, transfer_file_id):
    """Helper: POST /transfers/{id}/complete-upload/ with a canonical happy
    path body (single part, arbitrary ETag). Tests that need custom bodies
    (empty parts, bogus ETag) should inline the call instead."""
    return authenticated_client.post(
        f"{API_URL}{transfer_id}/complete-upload/",
        {
            "transfer_file_id": transfer_file_id,
            "parts": [{"PartNumber": 1, "ETag": '"etag-1"'}],
        },
        format="json",
    )


def _finalize(authenticated_client, transfer_id, **metadata):
    """Helper: POST /transfers/{id}/finalize/. Empty body works — every
    field on ``TransferFinalizeSerializer`` has a default that keeps the
    transfer coherent (link mode, no recipients, default expiry)."""
    return authenticated_client.post(
        f"{API_URL}{transfer_id}/finalize/", metadata, format="json",
    )


def _setup_draft_with_files(authenticated_client, file_specs):
    """Create a draft and attach each file in ``file_specs`` (a list of
    ``{"filename", "size", ...}`` dicts). Returns ``(transfer_id, [ids])``
    so callers can reference individual TransferFile rows.
    """
    initiate_resp = _add_file(authenticated_client, **file_specs[0])
    assert initiate_resp.status_code == 201, initiate_resp.data
    transfer_id = initiate_resp.data["transfer_id"]
    file_ids = [initiate_resp.data["transfer_file_id"]]
    for spec in file_specs[1:]:
        resp = _add_file(
            authenticated_client, transfer_id=transfer_id, **spec
        )
        assert resp.status_code == 201, resp.data
        file_ids.append(resp.data["transfer_file_id"])
    return transfer_id, file_ids


@pytest.mark.django_db
class TestTransferAddFile:
    """Covers POST /transfers/add-file/ — the single entry point for attaching
    files to a draft. Calling it without ``transfer_id`` opens a new draft as
    a side-effect; subsequent calls with ``transfer_id`` attach to the same
    draft. There is no separate "create" endpoint.
    """

    def test_unauthenticated(self, api_client):
        response = api_client.post(
            ADD_FILE_URL,
            {"filename": "a.bin", "size": 100},
            format="json",
        )
        assert response.status_code == 401

    def test_create_method_not_allowed(self, authenticated_client):
        # The bare POST /transfers/ route was removed with the refactor; any
        # attempt to reach it must 405 so clients rely on /add-file/ instead.
        response = authenticated_client.post(
            API_URL, {"files": [{"filename": "a.bin", "size": 1}]}, format="json"
        )
        assert response.status_code == 405

    def test_first_drop_opens_draft(
        self, patched_s3, authenticated_client, user
    ):
        response = _add_file(
            authenticated_client,
            filename="report.pdf",
            size=25 * 1024 * 1024,
            mime_type="application/pdf",
        )
        assert response.status_code == 201, response.data
        assert "transfer_id" in response.data
        assert response.data["chunk_size"] > 0
        assert response.data["upload_id"] == "FAKE-UPLOAD-ID"

        transfer = Transfer.objects.get(id=response.data["transfer_id"])
        assert transfer.owner == user
        assert transfer.status == TransferStatus.ACTIVE
        # Metadata is frozen at finalize time, not here — the draft carries
        # only placeholder defaults.
        assert transfer.title == ""
        assert transfer.public_token is None
        assert transfer.upload_completed_at is None
        assert transfer.files.count() == 1

        tf = transfer.files.get()
        assert tf.filename == "report.pdf"
        assert tf.size == 25 * 1024 * 1024
        assert tf.mime_type == "application/pdf"
        assert tf.upload_id == "FAKE-UPLOAD-ID"
        assert tf.upload_completed_at is None
        assert tf.s3_key.startswith(f"transfers/{transfer.id}/")
        patched_s3.create.assert_called_once()

    def test_first_drop_sets_placeholder_expiry(
        self, patched_s3, authenticated_client
    ):
        # ``expires_at`` is required on the model, so the draft gets a
        # default-window placeholder that ``finalize`` will overwrite.
        response = _add_file(authenticated_client)
        assert response.status_code == 201
        transfer = Transfer.objects.get(id=response.data["transfer_id"])
        delta = (transfer.expires_at - transfer.created_at).total_seconds()
        assert delta == pytest.approx(30 * 86400, abs=1)

    def test_subsequent_drop_attaches_to_same_draft(
        self, patched_s3, authenticated_client
    ):
        initiate = _initiate_with_file(authenticated_client)
        # Second drop — passes the draft id back in the body.
        response = _add_file(
            authenticated_client,
            transfer_id=initiate["transfer_id"],
            filename="second.bin",
            size=200,
        )
        assert response.status_code == 201, response.data
        assert response.data["transfer_id"] == initiate["transfer_id"]

        transfer = Transfer.objects.get(id=initiate["transfer_id"])
        names = sorted(f.filename for f in transfer.files.all())
        assert names == ["a.bin", "second.bin"]
        assert patched_s3.create.call_count == 2

    def test_subsequent_drop_rejects_finalized(
        self, patched_s3, authenticated_client, user
    ):
        transfer = TransferFactory(owner=user)  # already finalized
        response = _add_file(
            authenticated_client,
            transfer_id=transfer.id,
            filename="late.bin",
            size=1,
        )
        assert response.status_code == 403

    def test_subsequent_drop_rejects_other_user(
        self, patched_s3, authenticated_client
    ):
        other = TransferFactory()  # owned by someone else
        response = _add_file(
            authenticated_client,
            transfer_id=other.id,
            filename="x.bin",
            size=1,
        )
        assert response.status_code == 404

    def test_subsequent_drop_rejects_unknown_transfer(
        self, patched_s3, authenticated_client
    ):
        import uuid as _uuid

        response = _add_file(
            authenticated_client,
            transfer_id=_uuid.uuid4(),
            filename="x.bin",
            size=1,
        )
        assert response.status_code == 404

    def test_rejects_file_too_large(
        self, patched_s3, authenticated_client, settings
    ):
        response = _add_file(
            authenticated_client,
            filename="huge.bin",
            size=settings.TRANSFER_MAX_FILE_SIZE + 1,
        )
        assert response.status_code == 400

    def test_rejects_cumulative_total_size(
        self, patched_s3, authenticated_client, settings
    ):
        # Per-file limit is bumped so each individual drop passes, but the
        # cumulative total on the draft busts the transfer-level ceiling.
        settings.TRANSFER_MAX_FILE_SIZE = 100
        settings.TRANSFER_MAX_TOTAL_SIZE = 150
        initiate = _initiate_with_file(authenticated_client, size=80)
        response = _add_file(
            authenticated_client,
            transfer_id=initiate["transfer_id"],
            filename="b.bin",
            size=80,
        )
        assert response.status_code == 400
        assert "size" in response.data

    def test_rejects_cumulative_count_limit(
        self, patched_s3, authenticated_client, settings
    ):
        settings.TRANSFER_MAX_FILES_PER_TRANSFER = 2
        initiate = _initiate_with_file(authenticated_client, filename="a.bin")
        _add_file(
            authenticated_client,
            transfer_id=initiate["transfer_id"],
            filename="b.bin",
            size=1,
        )
        response = _add_file(
            authenticated_client,
            transfer_id=initiate["transfer_id"],
            filename="c.bin",
            size=1,
        )
        assert response.status_code == 400
        assert "files" in response.data

    def test_rejects_missing_filename(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            ADD_FILE_URL, {"size": 100}, format="json"
        )
        assert response.status_code == 400

    def test_rejects_missing_size(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            ADD_FILE_URL, {"filename": "a.bin"}, format="json"
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

    def test_sign_part_returns_url(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
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

    def test_complete_marks_file(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        response = _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )
        assert response.status_code == 204, response.data
        patched_s3.complete.assert_called_once()

        tf = TransferFile.objects.get(id=initiate["transfer_file_id"])
        assert tf.upload_completed_at is not None
        assert tf.upload_id == ""

        # complete-upload is a per-file S3 verb: it does NOT fire
        # TRANSFER_CREATED. That event is emitted only on finalize.
        transfer = Transfer.objects.get(id=initiate["transfer_id"])
        assert transfer.upload_completed_at is None
        assert transfer.public_token is None
        assert not TransferEvent.objects.filter(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_CREATED,
        ).exists()

    def test_complete_with_empty_parts_rejected(
        self, patched_s3, authenticated_client
    ):
        initiate = _initiate_with_file(authenticated_client)
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
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )
        # Second call should fail because upload is already complete.
        response = _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )
        assert response.status_code == 400

    def test_complete_rejects_other_user(self, patched_s3, authenticated_client):
        other_transfer = TransferFactory()
        tf = TransferFileFactory(transfer=other_transfer, upload_id="UPID")

        response = _complete_upload(
            authenticated_client, str(other_transfer.id), str(tf.id)
        )
        assert response.status_code == 404

    def test_complete_cleans_up_on_size_mismatch(
        self, patched_s3, authenticated_client
    ):
        # The client declared a 100-byte file but S3 ended up with 10 MB:
        # the backend must nuke the transfer.
        patched_s3.head.side_effect = None
        patched_s3.head.return_value = 10 * 1024 * 1024

        initiate = _initiate_with_file(authenticated_client)
        response = _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )

        assert response.status_code == 400
        assert "parts" in response.data
        assert "size" in str(response.data["parts"])
        assert not Transfer.objects.filter(id=initiate["transfer_id"]).exists()
        assert not TransferFile.objects.filter(
            id=initiate["transfer_file_id"]
        ).exists()

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

        initiate = _initiate_with_file(authenticated_client)
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
    """Covers POST /transfers/{id}/abort-upload/ — all-or-nothing teardown."""

    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(f"{API_URL}{transfer.id}/abort-upload/")
        assert response.status_code == 401

    def test_abort_deletes_transfer_and_calls_s3(
        self, patched_s3, authenticated_client
    ):
        initiate = _initiate_with_file(authenticated_client)

        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/abort-upload/"
        )
        assert response.status_code == 204
        patched_s3.abort.assert_called_once()

        assert not Transfer.objects.filter(id=initiate["transfer_id"]).exists()
        assert not TransferFile.objects.filter(
            id=initiate["transfer_file_id"]
        ).exists()

    def test_abort_multi_file_nukes_all(self, patched_s3, authenticated_client):
        transfer_id, _file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "size": 100},
                {"filename": "b.bin", "size": 200},
                {"filename": "c.bin", "size": 300},
            ],
        )

        response = authenticated_client.post(
            f"{API_URL}{transfer_id}/abort-upload/"
        )
        assert response.status_code == 204
        assert patched_s3.abort.call_count == 3
        assert not Transfer.objects.filter(id=transfer_id).exists()
        assert TransferFile.objects.filter(transfer_id=transfer_id).count() == 0

    def test_abort_rejects_finalized(self, patched_s3, authenticated_client, user):
        # A finalized transfer can't be aborted — use revoke instead.
        transfer = TransferFactory(owner=user)
        TransferFileFactory(transfer=transfer, upload_completed_at=timezone.now())

        response = authenticated_client.post(
            f"{API_URL}{transfer.id}/abort-upload/"
        )
        assert response.status_code == 400

    def test_abort_rejects_other_user(self, patched_s3, authenticated_client):
        other_transfer = TransferFactory(
            public_token=None, upload_completed_at=None
        )
        TransferFileFactory(transfer=other_transfer, upload_id="UPID")

        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/abort-upload/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestTransferFinalize:
    """Covers POST /transfers/{id}/finalize/ — all-or-nothing transition."""

    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(f"{API_URL}{transfer.id}/finalize/")
        assert response.status_code == 401

    def test_finalize_single_file(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )

        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/finalize/"
        )
        assert response.status_code == 200, response.data
        assert response.data["public_token"] is not None
        assert response.data["upload_completed_at"] is not None

        transfer = Transfer.objects.get(id=initiate["transfer_id"])
        assert transfer.public_token is not None
        assert transfer.upload_completed_at is not None
        assert_single_event(transfer.id, TransferEventType.TRANSFER_CREATED)

    def test_finalize_multi_file(self, patched_s3, authenticated_client):
        transfer_id, file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "size": 100},
                {"filename": "b.bin", "size": 200},
            ],
        )
        for tf_id in file_ids:
            _complete_upload(authenticated_client, transfer_id, tf_id)

        response = _finalize(authenticated_client, transfer_id)
        assert response.status_code == 200, response.data
        assert response.data["public_token"] is not None
        assert_single_event(transfer_id, TransferEventType.TRANSFER_CREATED)

    def test_finalize_rejects_pending_files(
        self, patched_s3, authenticated_client
    ):
        transfer_id, file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "size": 100},
                {"filename": "b.bin", "size": 200},
            ],
        )
        # Complete only the first file.
        _complete_upload(authenticated_client, transfer_id, file_ids[0])

        response = _finalize(authenticated_client, transfer_id)
        assert response.status_code == 400
        assert "files" in response.data
        assert "pending_file_ids" in response.data
        assert response.data["pending_file_ids"] == [file_ids[1]]

        transfer = Transfer.objects.get(id=transfer_id)
        assert transfer.public_token is None
        assert transfer.upload_completed_at is None

    def test_finalize_is_idempotent(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )
        r1 = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/finalize/"
        )
        r2 = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/finalize/"
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.data["public_token"] == r2.data["public_token"]
        # The event should have been emitted exactly once.
        assert_single_event(
            initiate["transfer_id"], TransferEventType.TRANSFER_CREATED
        )

    def test_finalize_rejects_other_user(self, patched_s3, authenticated_client):
        other = TransferFactory(public_token=None, upload_completed_at=None)
        TransferFileFactory(
            transfer=other, upload_completed_at=timezone.now()
        )
        response = authenticated_client.post(
            f"{API_URL}{other.id}/finalize/"
        )
        assert response.status_code == 404

    def test_finalize_applies_metadata(
        self, patched_s3, authenticated_client
    ):
        # Metadata is frozen here, not at draft-creation time. Verify that
        # the body's title / sharing_mode / recipients / sensitive /
        # expires_in_days all land on the transfer in a single transition.
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )

        before_expires = Transfer.objects.get(
            id=initiate["transfer_id"]
        ).expires_at

        response = _finalize(
            authenticated_client,
            initiate["transfer_id"],
            title="Dossier Marché",
            sharing_mode="email",
            recipients=["alice@example.com", "bob@example.com"],
            sensitive=True,
            expires_in_days=7,
        )
        assert response.status_code == 200, response.data

        transfer = Transfer.objects.get(id=initiate["transfer_id"])
        assert transfer.title == "Dossier Marché"
        assert transfer.sharing_mode == "email"
        assert transfer.sensitive is True
        # expires_at is re-anchored from *now* at finalize, not from the
        # draft's placeholder. The new value should differ from the one
        # set at draft creation.
        assert transfer.expires_at != before_expires
        delta = (transfer.expires_at - timezone.now()).total_seconds()
        assert delta == pytest.approx(7 * 86400, abs=5)
        recipients = sorted(r.email for r in transfer.recipients.all())
        assert recipients == ["alice@example.com", "bob@example.com"]

    def test_finalize_rejects_email_mode_without_recipients(
        self, patched_s3, authenticated_client
    ):
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )
        response = _finalize(
            authenticated_client,
            initiate["transfer_id"],
            sharing_mode="email",
            recipients=[],
        )
        assert response.status_code == 400
        assert "recipients" in response.data

    def test_finalize_rejects_link_mode_with_recipients(
        self, patched_s3, authenticated_client
    ):
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )
        response = _finalize(
            authenticated_client,
            initiate["transfer_id"],
            sharing_mode="link",
            recipients=["alice@example.com"],
        )
        assert response.status_code == 400
        assert "recipients" in response.data

    def test_finalize_discards_recipients_when_mode_is_link(
        self, patched_s3, authenticated_client
    ):
        # Edge case: caller switches the draft from "email" to "link" right
        # before finalize — the final write should end up with zero recipients
        # regardless of what was locally buffered during the draft phase.
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["transfer_id"],
            initiate["transfer_file_id"],
        )
        response = _finalize(
            authenticated_client,
            initiate["transfer_id"],
            sharing_mode="link",
            # No ``recipients`` key → defaults to [] which is valid for link.
        )
        assert response.status_code == 200
        transfer = Transfer.objects.get(id=initiate["transfer_id"])
        assert transfer.recipients.count() == 0


@pytest.mark.django_db
class TestTransferRemoveFile:
    """Covers POST /transfers/{id}/remove-file/ — per-file detach on a draft."""

    def test_unauthenticated(self, api_client, transfer):
        response = api_client.post(
            f"{API_URL}{transfer.id}/remove-file/",
            {"transfer_file_id": str(transfer.id)},
            format="json",
        )
        assert response.status_code == 401

    def test_remove_existing_file(self, patched_s3, authenticated_client):
        transfer_id, file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "size": 100},
                {"filename": "b.bin", "size": 200},
            ],
        )

        response = authenticated_client.post(
            f"{API_URL}{transfer_id}/remove-file/",
            {"transfer_file_id": file_ids[0]},
            format="json",
        )
        assert response.status_code == 204
        # S3 best-effort cleanup was triggered.
        patched_s3.abort.assert_called()
        patched_s3.delete.assert_called()

        # The other file remains; the draft stays open.
        remaining = list(
            TransferFile.objects.filter(transfer_id=transfer_id).values_list(
                "filename", flat=True
            )
        )
        assert remaining == ["b.bin"]
        assert Transfer.objects.filter(id=transfer_id).exists()

    def test_remove_last_file_destroys_draft(
        self, patched_s3, authenticated_client
    ):
        # Empty drafts have no metadata of their own, so removing the final
        # file must take the parent Transfer down too — otherwise a client
        # that bypasses our frontend could leak headless drafts until the
        # abandoned-upload cron catches them at T+24h.
        initiate = _initiate_with_file(authenticated_client)

        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/remove-file/",
            {"transfer_file_id": initiate["transfer_file_id"]},
            format="json",
        )
        assert response.status_code == 204
        assert not Transfer.objects.filter(
            id=initiate["transfer_id"]
        ).exists()
        assert not TransferFile.objects.filter(
            id=initiate["transfer_file_id"]
        ).exists()

    def test_remove_unknown_file(self, patched_s3, authenticated_client):
        import uuid as _uuid

        initiate = _initiate_with_file(authenticated_client)
        response = authenticated_client.post(
            f"{API_URL}{initiate['transfer_id']}/remove-file/",
            {"transfer_file_id": str(_uuid.uuid4())},
            format="json",
        )
        assert response.status_code == 404

    def test_remove_on_finalized_rejected(
        self, patched_s3, authenticated_client, user
    ):
        # Finalized transfers are frozen — use revoke to tear them down.
        transfer = TransferFactory(owner=user)
        tf = TransferFileFactory(
            transfer=transfer, upload_completed_at=timezone.now()
        )
        response = authenticated_client.post(
            f"{API_URL}{transfer.id}/remove-file/",
            {"transfer_file_id": str(tf.id)},
            format="json",
        )
        assert response.status_code == 403

    def test_remove_rejects_other_user(self, patched_s3, authenticated_client):
        other_transfer = TransferFactory(
            public_token=None, upload_completed_at=None
        )
        tf = TransferFileFactory(transfer=other_transfer, upload_id="UPID")
        response = authenticated_client.post(
            f"{API_URL}{other_transfer.id}/remove-file/",
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
