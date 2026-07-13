"""Tests for the Draft API endpoints (authenticated agent).

Covers the whole upload lifecycle on ``/api/v1.0/drafts/``: add-file
(which doubles as draft-opener on the first call), sign-part,
complete-upload, remove-file, abort, finalize. The ``patched_s3`` fixture
in ``conftest.py`` mocks out every S3 helper so tests run without object
storage.

Sibling file ``test_api_transfers.py`` exercises the read-only / deactivate
endpoints on the public Transfer surface.
"""

import uuid as _uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.utils import timezone

import pytest
from botocore.exceptions import ClientError

from core.enums import ScanStatus, TransferEventType
from core.factories import (
    TransferDraftFactory,
    TransferFactory,
    TransferFileFactory,
)
from core.models import Transfer, TransferDraft, TransferEvent, TransferFile
from core.tests.conftest import assert_single_event

TRANSFERS_URL = "/api/v1.0/transfers/"
DRAFTS_URL = "/api/v1.0/drafts/"
ADD_FILE_URL = f"{DRAFTS_URL}add-file/"

# Every transfer is encrypted now, so add-file always carries a
# ``plaintext_size`` and a ``size`` that equals the ciphertext expansion,
# and finalize carries the key unless the transfer is confidential.
CHUNK = 25 * 1024 * 1024
OVERHEAD = 28  # per-chunk IV (12) + GCM tag (16)
# 43-char URL-safe base64 of 32 zero bytes — a structurally valid key the
# serializer accepts and the import task can decode.
VALID_KEY = "A" * 43


def _ciphertext_size(plaintext_size, chunk_size=CHUNK):
    """Ciphertext bytes that land in S3 for a plaintext of this size, matching
    the browser's layout and the backend's ``_expected_ciphertext_size``."""
    if plaintext_size <= 0:
        return OVERHEAD
    chunks = -(-plaintext_size // chunk_size)  # ceil division
    return plaintext_size + chunks * OVERHEAD


# --- Helpers ---


def _add_file(authenticated_client, draft_id=None, **file_body):
    """POST /drafts/add-file/. Omit ``draft_id`` for the first drop (opens
    the draft as a side-effect); pass it on subsequent drops to attach the
    file to the same draft.

    Defaults to a coherent encrypted file: ``plaintext_size`` 100 and a
    ``size`` that matches the ciphertext expansion. A test can override
    either; ``size`` defaults to match whatever ``plaintext_size`` ends up
    being unless the test passes ``size`` explicitly.
    """
    body = {"filename": "a.bin"}
    body.update(file_body)
    body.setdefault("plaintext_size", 100)
    body.setdefault("size", _ciphertext_size(body["plaintext_size"]))
    if draft_id is not None:
        body["draft_id"] = str(draft_id)
    return authenticated_client.post(ADD_FILE_URL, body, format="json")


def _initiate_with_file(authenticated_client, **file_body):
    """First-drop helper: opens a draft + attaches one file. Returns the
    response fields downstream tests need to wire sign-part / complete-upload
    / finalize."""
    resp = _add_file(authenticated_client, **file_body)
    assert resp.status_code == 201, resp.data
    return {
        "draft_id": resp.data["draft_id"],
        "transfer_file_id": resp.data["transfer_file_id"],
        "upload_id": resp.data["upload_id"],
        "s3_key": resp.data["s3_key"],
        "chunk_size": resp.data["chunk_size"],
    }


def _complete_upload(authenticated_client, draft_id, transfer_file_id):
    """POST /drafts/{id}/complete-upload/ with a canonical single-part body."""
    return authenticated_client.post(
        f"{DRAFTS_URL}{draft_id}/complete-upload/",
        {
            "transfer_file_id": transfer_file_id,
            "parts": [{"PartNumber": 1, "ETag": '"etag-1"'}],
        },
        format="json",
    )


def _finalize(authenticated_client, draft_id, **metadata):
    """POST /drafts/{id}/finalize/.

    Defaults to a non-confidential transfer and supplies the ``encryption_key``
    the backend now requires in that mode. A test exercising confidential mode
    passes ``confidential=True`` (and no key); a test can override the key.
    """
    body = dict(metadata)
    if not body.get("confidential"):
        body.setdefault("encryption_key", VALID_KEY)
    return authenticated_client.post(
        f"{DRAFTS_URL}{draft_id}/finalize/",
        body,
        format="json",
    )


def _setup_draft_with_files(authenticated_client, file_specs):
    """Open a draft and attach each file in ``file_specs`` (a list of
    ``{"filename", "size", ...}`` dicts). Returns ``(draft_id, [file_ids])``.
    """
    initiate_resp = _add_file(authenticated_client, **file_specs[0])
    assert initiate_resp.status_code == 201, initiate_resp.data
    draft_id = initiate_resp.data["draft_id"]
    file_ids = [initiate_resp.data["transfer_file_id"]]
    for spec in file_specs[1:]:
        resp = _add_file(authenticated_client, draft_id=draft_id, **spec)
        assert resp.status_code == 201, resp.data
        file_ids.append(resp.data["transfer_file_id"])
    return draft_id, file_ids


# --- Tests ---


@pytest.mark.django_db
class TestDraftAddFile:
    """POST /drafts/add-file/ — single entry point for attaching files to
    a draft. Called without ``draft_id`` it opens a new draft as a side-
    effect; subsequent calls with ``draft_id`` attach to the same draft.
    There is no separate "create draft" endpoint.
    """

    def test_unauthenticated(self, api_client):
        response = api_client.post(
            ADD_FILE_URL,
            {"filename": "a.bin", "size": 100},
            format="json",
        )
        assert response.status_code == 401

    def test_transfers_post_is_method_not_allowed(self, authenticated_client):
        # The bare POST /transfers/ route was removed with the refactor; any
        # attempt to reach it must 405 so clients rely on /drafts/add-file/.
        response = authenticated_client.post(
            TRANSFERS_URL,
            {"files": [{"filename": "a.bin", "size": 1}]},
            format="json",
        )
        assert response.status_code == 405

    def test_first_drop_opens_draft(self, patched_s3, authenticated_client, user):
        response = _add_file(
            authenticated_client,
            filename="report.pdf",
            plaintext_size=1000,
            mime_type="application/pdf",
        )
        assert response.status_code == 201, response.data
        assert "draft_id" in response.data
        assert response.data["chunk_size"] > 0
        assert response.data["upload_id"] == "FAKE-UPLOAD-ID"

        draft = TransferDraft.objects.get(id=response.data["draft_id"])
        assert draft.owner == user
        assert draft.files.count() == 1
        # Every draft is encrypted now, so the chunk size is always set.
        assert draft.encryption_chunk_size == CHUNK
        # No Transfer row exists yet — that only happens at finalize.
        assert not Transfer.objects.filter(owner=user).exists()

        tf = draft.files.get()
        assert tf.filename == "report.pdf"
        # ``size`` is the ciphertext that lands in S3; ``plaintext_size`` is
        # the original file size.
        assert tf.plaintext_size == 1000
        assert tf.size == 1000 + OVERHEAD
        assert tf.mime_type == "application/pdf"
        assert tf.upload_id == "FAKE-UPLOAD-ID"
        assert tf.upload_completed_at is None
        # S3 key is scoped to the TransferFile UUID — stable across the
        # finalize-time reparenting that swaps draft→transfer.
        assert tf.s3_key == f"transfers/{tf.id}/report.pdf"
        patched_s3.create.assert_called_once()

    def test_subsequent_drop_attaches_to_same_draft(
        self, patched_s3, authenticated_client
    ):
        initiate = _initiate_with_file(authenticated_client)
        response = _add_file(
            authenticated_client,
            draft_id=initiate["draft_id"],
            filename="second.bin",
            plaintext_size=200,
        )
        assert response.status_code == 201, response.data
        assert response.data["draft_id"] == initiate["draft_id"]

        draft = TransferDraft.objects.get(id=initiate["draft_id"])
        names = sorted(f.filename for f in draft.files.all())
        assert names == ["a.bin", "second.bin"]
        assert patched_s3.create.call_count == 2

    def test_subsequent_drop_rejects_other_user(self, patched_s3, authenticated_client):
        other = TransferDraftFactory()  # owned by someone else
        response = _add_file(
            authenticated_client,
            draft_id=other.id,
            filename="x.bin",
        )
        assert response.status_code == 404

    def test_subsequent_drop_rejects_unknown_draft(
        self, patched_s3, authenticated_client
    ):
        response = _add_file(
            authenticated_client,
            draft_id=_uuid.uuid4(),
            filename="x.bin",
        )
        assert response.status_code == 404

    def test_rejects_file_too_large(self, patched_s3, authenticated_client, settings):
        response = _add_file(
            authenticated_client,
            filename="huge.bin",
            size=settings.TRANSFER_MAX_FILE_SIZE + 1,
        )
        assert response.status_code == 400

    def test_rejects_cumulative_total_size(
        self, patched_s3, authenticated_client, settings
    ):
        # Per-file limit bumped so each drop passes individually; cumulative
        # total on the draft busts the transfer-level ceiling.
        settings.TRANSFER_MAX_FILE_SIZE = 100
        settings.TRANSFER_MAX_TOTAL_SIZE = 150
        # plaintext 52 → ciphertext 80; two of them (160) bust the 150 cap.
        initiate = _initiate_with_file(authenticated_client, plaintext_size=52)
        response = _add_file(
            authenticated_client,
            draft_id=initiate["draft_id"],
            filename="b.bin",
            plaintext_size=52,
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
            draft_id=initiate["draft_id"],
            filename="b.bin",
        )
        response = _add_file(
            authenticated_client,
            draft_id=initiate["draft_id"],
            filename="c.bin",
        )
        assert response.status_code == 400
        assert "files" in response.data

    def test_rejects_missing_filename(self, patched_s3, authenticated_client):
        response = authenticated_client.post(ADD_FILE_URL, {"size": 100}, format="json")
        assert response.status_code == 400

    def test_rejects_missing_size(self, patched_s3, authenticated_client):
        response = authenticated_client.post(
            ADD_FILE_URL, {"filename": "a.bin"}, format="json"
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestDraftSignPart:
    """POST /drafts/{id}/sign-part/."""

    def test_unauthenticated(self, api_client):
        draft = TransferDraftFactory()
        response = api_client.post(
            f"{DRAFTS_URL}{draft.id}/sign-part/",
            {"transfer_file_id": str(_uuid.uuid4()), "part_number": 1},
            format="json",
        )
        assert response.status_code == 401

    def test_sign_part_returns_url(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        response = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/sign-part/",
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
        other_draft = TransferDraftFactory()
        tf = TransferFileFactory(transfer=None, draft=other_draft, upload_id="UPID")
        response = authenticated_client.post(
            f"{DRAFTS_URL}{other_draft.id}/sign-part/",
            {"transfer_file_id": str(tf.id), "part_number": 1},
            format="json",
        )
        assert response.status_code == 404  # filtered by owner queryset

    def test_sign_part_after_completion_rejected(
        self, patched_s3, authenticated_client, user
    ):
        draft = TransferDraftFactory(owner=user)
        tf = TransferFileFactory(
            transfer=None,
            draft=draft,
            upload_id="",
            upload_completed_at=timezone.now(),
        )
        response = authenticated_client.post(
            f"{DRAFTS_URL}{draft.id}/sign-part/",
            {"transfer_file_id": str(tf.id), "part_number": 1},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestDraftCompleteUpload:
    """POST /drafts/{id}/complete-upload/."""

    def test_unauthenticated(self, api_client):
        draft = TransferDraftFactory()
        response = api_client.post(
            f"{DRAFTS_URL}{draft.id}/complete-upload/",
            {
                "transfer_file_id": str(_uuid.uuid4()),
                "parts": [{"PartNumber": 1, "ETag": '"e"'}],
            },
            format="json",
        )
        assert response.status_code == 401

    def test_complete_marks_file(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        response = _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        assert response.status_code == 204, response.data
        patched_s3.complete.assert_called_once()

        tf = TransferFile.objects.get(id=initiate["transfer_file_id"])
        assert tf.upload_completed_at is not None
        assert tf.upload_id == ""

        # complete-upload is a per-file S3 verb — no Transfer row created,
        # no TRANSFER_CREATED event yet. Only finalize does that.
        assert not Transfer.objects.exists()
        assert not TransferEvent.objects.filter(
            event_type=TransferEventType.TRANSFER_CREATED,
        ).exists()

    def test_complete_with_empty_parts_rejected(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        response = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/complete-upload/",
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
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        # Second call should fail because upload is already complete.
        response = _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        assert response.status_code == 400

    def test_complete_rejects_other_user(self, patched_s3, authenticated_client):
        other_draft = TransferDraftFactory()
        tf = TransferFileFactory(transfer=None, draft=other_draft, upload_id="UPID")
        response = _complete_upload(
            authenticated_client, str(other_draft.id), str(tf.id)
        )
        assert response.status_code == 404

    def test_complete_cleans_up_on_size_mismatch(
        self, patched_s3, authenticated_client
    ):
        # Client declared a 100-byte file but S3 has 10 MB — backend nukes
        # the whole draft.
        patched_s3.head.side_effect = None
        patched_s3.head.return_value = 10 * 1024 * 1024

        initiate = _initiate_with_file(authenticated_client)
        response = _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )

        assert response.status_code == 400
        assert "parts" in response.data
        assert "size" in str(response.data["parts"])
        assert not TransferDraft.objects.filter(id=initiate["draft_id"]).exists()
        assert not TransferFile.objects.filter(id=initiate["transfer_file_id"]).exists()

    def test_complete_cleans_up_on_s3_error(self, patched_s3, authenticated_client):
        patched_s3.complete.side_effect = ClientError(
            {
                "Error": {
                    "Code": "InvalidPart",
                    "Message": "One or more of the specified parts could not be found",
                }
            },
            "CompleteMultipartUpload",
        )

        initiate = _initiate_with_file(authenticated_client)
        response = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/complete-upload/",
            {
                "transfer_file_id": initiate["transfer_file_id"],
                "parts": [{"PartNumber": 1, "ETag": '"bogus"'}],
            },
            format="json",
        )

        assert response.status_code == 400
        assert "parts" in response.data
        assert "InvalidPart" in str(response.data["parts"])

        patched_s3.abort.assert_called_once()
        assert not TransferDraft.objects.filter(id=initiate["draft_id"]).exists()
        assert not TransferFile.objects.filter(id=initiate["transfer_file_id"]).exists()


@pytest.mark.django_db
class TestDraftAbort:
    """POST /drafts/{id}/abort/ — all-or-nothing teardown of a draft."""

    def test_unauthenticated(self, api_client):
        draft = TransferDraftFactory()
        response = api_client.post(f"{DRAFTS_URL}{draft.id}/abort/")
        assert response.status_code == 401

    def test_abort_deletes_draft_and_calls_s3(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)

        response = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/abort/"
        )
        assert response.status_code == 204
        patched_s3.abort.assert_called_once()
        patched_s3.delete.assert_called_once()

        assert not TransferDraft.objects.filter(id=initiate["draft_id"]).exists()
        assert not TransferFile.objects.filter(id=initiate["transfer_file_id"]).exists()

    def test_abort_multi_file_nukes_all(self, patched_s3, authenticated_client):
        draft_id, _file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "plaintext_size": 100},
                {"filename": "b.bin", "plaintext_size": 200},
                {"filename": "c.bin", "plaintext_size": 300},
            ],
        )

        response = authenticated_client.post(f"{DRAFTS_URL}{draft_id}/abort/")
        assert response.status_code == 204
        assert patched_s3.abort.call_count == 3
        assert patched_s3.delete.call_count == 3
        assert not TransferDraft.objects.filter(id=draft_id).exists()
        assert TransferFile.objects.filter(draft_id=draft_id).count() == 0

    def test_abort_rejects_other_user(self, patched_s3, authenticated_client):
        other_draft = TransferDraftFactory()
        TransferFileFactory(transfer=None, draft=other_draft, upload_id="UPID")

        response = authenticated_client.post(f"{DRAFTS_URL}{other_draft.id}/abort/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestDraftFinalize:
    """POST /drafts/{id}/finalize/ — creates the Transfer + reparents files."""

    def test_unauthenticated(self, api_client):
        draft = TransferDraftFactory()
        response = api_client.post(f"{DRAFTS_URL}{draft.id}/finalize/")
        assert response.status_code == 401

    def test_finalize_single_file(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )

        response = _finalize(authenticated_client, initiate["draft_id"])
        assert response.status_code == 200, response.data
        assert response.data["public_token"] is not None

        # Draft is gone; Transfer exists under a fresh id.
        assert not TransferDraft.objects.filter(id=initiate["draft_id"]).exists()
        transfer = Transfer.objects.get(id=response.data["id"])
        assert transfer.public_token is not None
        # Transfer rows only exist post-finalize, so created_at ≈ now.
        assert (timezone.now() - transfer.created_at).total_seconds() < 5
        assert_single_event(transfer.id, TransferEventType.TRANSFER_CREATED)

    def test_finalize_reparents_files(self, patched_s3, authenticated_client):
        """The TransferFile rows carry over from draft to transfer — same
        UUIDs, same S3 keys, just a swapped FK."""
        draft_id, file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "plaintext_size": 100},
                {"filename": "b.bin", "plaintext_size": 200},
            ],
        )
        for tf_id in file_ids:
            _complete_upload(authenticated_client, draft_id, tf_id)

        response = _finalize(authenticated_client, draft_id)
        assert response.status_code == 200
        transfer_id = response.data["id"]

        # File rows kept their IDs but now point to the Transfer, not the draft.
        for tf_id in file_ids:
            tf = TransferFile.objects.get(id=tf_id)
            assert tf.transfer_id == _uuid.UUID(transfer_id)
            assert tf.draft_id is None
        # Draft row is deleted.
        assert not TransferDraft.objects.filter(id=draft_id).exists()

    def test_finalize_multi_file(self, patched_s3, authenticated_client):
        draft_id, file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "plaintext_size": 100},
                {"filename": "b.bin", "plaintext_size": 200},
            ],
        )
        for tf_id in file_ids:
            _complete_upload(authenticated_client, draft_id, tf_id)

        response = _finalize(authenticated_client, draft_id)
        assert response.status_code == 200, response.data
        assert response.data["public_token"] is not None
        assert_single_event(response.data["id"], TransferEventType.TRANSFER_CREATED)

    def test_finalize_rejects_pending_files(self, patched_s3, authenticated_client):
        draft_id, file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "plaintext_size": 100},
                {"filename": "b.bin", "plaintext_size": 200},
            ],
        )
        # Complete only the first file.
        _complete_upload(authenticated_client, draft_id, file_ids[0])

        response = _finalize(authenticated_client, draft_id)
        assert response.status_code == 400
        assert "files" in response.data
        assert "pending_file_ids" in response.data
        assert response.data["pending_file_ids"] == [file_ids[1]]

        # Draft stays (only the finalize fails); no Transfer created.
        assert TransferDraft.objects.filter(id=draft_id).exists()
        assert Transfer.objects.count() == 0

    def test_finalize_rejects_empty_draft(self, patched_s3, authenticated_client, user):
        # A draft with zero files can't be finalized — nothing to publish.
        draft = TransferDraftFactory(owner=user)
        response = _finalize(authenticated_client, draft.id)
        assert response.status_code == 400
        assert "files" in response.data

    def test_finalize_rejects_other_user(self, patched_s3, authenticated_client):
        other_draft = TransferDraftFactory()
        TransferFileFactory(
            transfer=None,
            draft=other_draft,
            upload_completed_at=timezone.now(),
        )
        # Valid body so serializer validation passes and we reach the
        # ownership check (404), not a 400 on the missing key.
        response = _finalize(authenticated_client, other_draft.id)
        assert response.status_code == 404

    def test_finalize_applies_metadata(self, patched_s3, authenticated_client):
        # Metadata is frozen here, not at draft-creation time. Verify the
        # body's fields all land on the newly-created transfer in one write.
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )

        response = _finalize(
            authenticated_client,
            initiate["draft_id"],
            title="Dossier Marché",
            sharing_mode="email",
            recipients=["alice@example.com", "bob@example.com"],
            expires_in_days=7,
        )
        assert response.status_code == 200, response.data

        transfer = Transfer.objects.get(id=response.data["id"])
        assert transfer.title == "Dossier Marché"
        assert transfer.sharing_mode == "email"
        # expires_at is anchored at finalize time.
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
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        response = _finalize(
            authenticated_client,
            initiate["draft_id"],
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
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        response = _finalize(
            authenticated_client,
            initiate["draft_id"],
            sharing_mode="link",
            recipients=["alice@example.com"],
        )
        assert response.status_code == 400
        assert "recipients" in response.data

    def test_finalize_discards_recipients_when_mode_is_link(
        self, patched_s3, authenticated_client
    ):
        # Caller switches from email to link right before finalize — the
        # resulting transfer should have zero recipients whatever was
        # locally buffered during the draft phase.
        initiate = _initiate_with_file(authenticated_client)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        response = _finalize(
            authenticated_client,
            initiate["draft_id"],
            sharing_mode="link",
        )
        assert response.status_code == 200
        transfer = Transfer.objects.get(id=response.data["id"])
        assert transfer.recipients.count() == 0


@pytest.mark.django_db
class TestDraftEncryption:
    """Every transfer is encrypted client-side. The ``confidential`` flag,
    chosen at finalize, decides whether the backend stores the key (normal,
    served to recipients) or never sees it (confidential). These tests cover
    the bookkeeping; the crypto itself is browser-side (and, for Drive
    imports, in ``core.services.encryption``)."""

    def test_every_draft_is_encrypted(self, patched_s3, authenticated_client):
        resp = _add_file(authenticated_client, plaintext_size=1024)
        assert resp.status_code == 201, resp.data

        draft = TransferDraft.objects.get(id=resp.data["draft_id"])
        assert draft.encryption_chunk_size == CHUNK

        tf = draft.files.get()
        assert tf.size == 1024 + OVERHEAD
        assert tf.plaintext_size == 1024

    def test_add_file_requires_plaintext_size(
        self, patched_s3, authenticated_client
    ):
        resp = authenticated_client.post(
            ADD_FILE_URL,
            {"filename": "a.bin", "size": 2048},
            format="json",
        )
        assert resp.status_code == 400
        assert "plaintext_size" in resp.data

    def test_multi_chunk_file_accepted(self, patched_s3, authenticated_client):
        # A file larger than one chunk produces ceil(N/chunk) crypto chunks,
        # each adding OVERHEAD bytes. Exercise the most off-by-one-prone
        # case: chunk+1 plaintext bytes ⇒ 2 chunks.
        plaintext = CHUNK + 1
        resp = _add_file(authenticated_client, plaintext_size=plaintext)
        assert resp.status_code == 201, resp.data

        tf = TransferFile.objects.get(id=resp.data["transfer_file_id"])
        assert tf.plaintext_size == plaintext
        assert tf.size == plaintext + 2 * OVERHEAD

    def test_rejects_size_mismatch(self, patched_s3, authenticated_client):
        # Lying about ``size`` against the canonical chunk size would let a
        # client poison the file row so the recipient SW computes decryption
        # boundaries that don't match the bytes in S3. The serializer
        # recomputes the expected size and rejects any divergence.
        plaintext = 1024
        resp = authenticated_client.post(
            ADD_FILE_URL,
            {
                "filename": "a.bin",
                "size": _ciphertext_size(plaintext) + 1,  # off by one
                "plaintext_size": plaintext,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert "size" in resp.data

    def test_complete_upload_marks_skipped(
        self, patched_s3, authenticated_client, settings
    ):
        # Encrypted ciphertext can't be scanned, so the file lands SKIPPED
        # even with the scanner enabled — the finalize gate lets it through.
        settings.CLAMAV_SCAN_ENABLED = True
        initiate = _initiate_with_file(authenticated_client, plaintext_size=1024)
        with patch("core.api.viewsets.draft.submit_scan_task.delay") as scan_mock:
            resp = _complete_upload(
                authenticated_client,
                initiate["draft_id"],
                initiate["transfer_file_id"],
            )
        assert resp.status_code == 204, resp.data
        scan_mock.assert_not_called()

        from core.enums import ScanStatus

        tf = TransferFile.objects.get(id=initiate["transfer_file_id"])
        assert tf.scan_status == ScanStatus.SKIPPED

    def test_finalize_normal_stores_key(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client, plaintext_size=1024)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        resp = _finalize(authenticated_client, initiate["draft_id"])
        assert resp.status_code == 200, resp.data

        transfer = Transfer.objects.get(id=resp.data["id"])
        assert transfer.confidential is False
        assert transfer.encryption_key == VALID_KEY
        assert transfer.encryption_chunk_size == CHUNK
        assert transfer.files.get().plaintext_size == 1024
        # Detail echoes confidential + chunk size (but not the key).
        assert resp.data["confidential"] is False
        assert resp.data["encryption_chunk_size"] == CHUNK

    def test_finalize_confidential_stores_no_key(
        self, patched_s3, authenticated_client
    ):
        initiate = _initiate_with_file(authenticated_client, plaintext_size=1024)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        resp = _finalize(
            authenticated_client, initiate["draft_id"], confidential=True
        )
        assert resp.status_code == 200, resp.data

        transfer = Transfer.objects.get(id=resp.data["id"])
        assert transfer.confidential is True
        assert transfer.encryption_key == ""

    def test_finalize_rejects_key_when_confidential(
        self, patched_s3, authenticated_client
    ):
        # A confidential transfer must never post the key to us.
        initiate = _initiate_with_file(authenticated_client, plaintext_size=1024)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        resp = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/finalize/",
            {"confidential": True, "encryption_key": VALID_KEY},
            format="json",
        )
        assert resp.status_code == 400
        assert "encryption_key" in resp.data

    def test_finalize_rejects_missing_key_when_normal(
        self, patched_s3, authenticated_client
    ):
        # A non-confidential transfer needs the key so we can serve it to
        # recipients; missing it is a 400.
        initiate = _initiate_with_file(authenticated_client, plaintext_size=1024)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        resp = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/finalize/",
            {},  # confidential defaults to False, no key
            format="json",
        )
        assert resp.status_code == 400
        assert "encryption_key" in resp.data

    def test_finalize_confidential_email_is_allowed(
        self, patched_s3, authenticated_client
    ):
        # Confidential works in email mode too: the email carries only the
        # bare link, the recipient pastes the key. No key reaches us.
        initiate = _initiate_with_file(authenticated_client, plaintext_size=1024)
        _complete_upload(
            authenticated_client,
            initiate["draft_id"],
            initiate["transfer_file_id"],
        )
        with patch("core.tasks.send_recipient_invitations_task.delay"):
            resp = _finalize(
                authenticated_client,
                initiate["draft_id"],
                confidential=True,
                sharing_mode="email",
                recipients=["a@b.fr"],
            )
        assert resp.status_code == 200, resp.data
        assert Transfer.objects.get(id=resp.data["id"]).confidential is True

    def test_confidential_with_drive_rejected_at_finalize(
        self, patched_s3, authenticated_client
    ):
        # Drive import needs the key server-side, which a confidential
        # transfer withholds — so the combo is rejected.
        resp = _add_file(
            authenticated_client,
            plaintext_size=1024,
            source_url="https://drive.example.com/x",
        )
        assert resp.status_code == 201, resp.data
        finalize = authenticated_client.post(
            f"{DRAFTS_URL}{resp.data['draft_id']}/finalize/",
            {"confidential": True},
            format="json",
        )
        assert finalize.status_code == 400
        assert "confidential" in finalize.data

    def test_normal_with_drive_kicks_off_import_and_returns_202(
        self, patched_s3, authenticated_client
    ):
        # Drive files are imported (and encrypted) at finalize: the first
        # call enqueues the import with the key and returns 202; the client
        # re-polls until the file lands.
        resp = _add_file(
            authenticated_client,
            plaintext_size=1024,
            source_url="https://drive.example.com/x",
        )
        assert resp.status_code == 201, resp.data
        with patch(
            "core.api.viewsets.draft.import_drive_file_task.delay"
        ) as import_mock:
            from django.test import TestCase as _TC

            with _TC.captureOnCommitCallbacks(execute=True):
                finalize = _finalize(authenticated_client, resp.data["draft_id"])
        assert finalize.status_code == 202, finalize.data
        assert finalize.data["reason"] == "drive_importing"
        import_mock.assert_called_once()
        # The key is passed to the import task so it can encrypt server-side.
        args = import_mock.call_args.args
        assert args[1] == VALID_KEY
        # No transfer yet — it's created only once the import lands.
        assert Transfer.objects.count() == 0

    def test_finalize_poll_does_not_re_enqueue_import(
        self, patched_s3, authenticated_client
    ):
        # The finalize poll is idempotent: re-posting while a Drive import is
        # still in flight returns 202 again without starting a second import.
        # ``import_started_at`` is the guard that makes the re-post a no-op.
        resp = _add_file(
            authenticated_client,
            plaintext_size=1024,
            source_url="https://drive.example.com/x",
        )
        assert resp.status_code == 201, resp.data
        draft_id = resp.data["draft_id"]
        from django.test import TestCase as _TC

        with patch(
            "core.api.viewsets.draft.import_drive_file_task.delay"
        ) as import_mock:
            with _TC.captureOnCommitCallbacks(execute=True):
                first = _finalize(authenticated_client, draft_id)
            assert first.status_code == 202, first.data
            tf = TransferFile.objects.get(draft_id=draft_id)
            assert tf.import_started_at is not None

            # Import still in flight (the task is mocked, so the file never
            # completes): a second poll stays 202 and does not re-enqueue.
            with _TC.captureOnCommitCallbacks(execute=True):
                second = _finalize(authenticated_client, draft_id)
            assert second.status_code == 202, second.data
            import_mock.assert_called_once()


@pytest.mark.django_db
class TestDraftRemoveFile:
    """POST /drafts/{id}/remove-file/."""

    def test_unauthenticated(self, api_client):
        draft = TransferDraftFactory()
        response = api_client.post(
            f"{DRAFTS_URL}{draft.id}/remove-file/",
            {"transfer_file_id": str(_uuid.uuid4())},
            format="json",
        )
        assert response.status_code == 401

    def test_remove_existing_file(self, patched_s3, authenticated_client):
        draft_id, file_ids = _setup_draft_with_files(
            authenticated_client,
            [
                {"filename": "a.bin", "plaintext_size": 100},
                {"filename": "b.bin", "plaintext_size": 200},
            ],
        )

        response = authenticated_client.post(
            f"{DRAFTS_URL}{draft_id}/remove-file/",
            {"transfer_file_id": file_ids[0]},
            format="json",
        )
        assert response.status_code == 204
        patched_s3.abort.assert_called()
        patched_s3.delete.assert_called()

        remaining = list(
            TransferFile.objects.filter(draft_id=draft_id).values_list(
                "filename", flat=True
            )
        )
        assert remaining == ["b.bin"]
        assert TransferDraft.objects.filter(id=draft_id).exists()

    def test_remove_last_file_destroys_draft(self, patched_s3, authenticated_client):
        # Empty drafts have no reason to exist — removing the last file
        # takes the draft with it, so clients that bypass our frontend
        # can't leak headless drafts until the cron sweeps them.
        initiate = _initiate_with_file(authenticated_client)

        response = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/remove-file/",
            {"transfer_file_id": initiate["transfer_file_id"]},
            format="json",
        )
        assert response.status_code == 204
        assert not TransferDraft.objects.filter(id=initiate["draft_id"]).exists()
        assert not TransferFile.objects.filter(id=initiate["transfer_file_id"]).exists()

    def test_remove_unknown_file(self, patched_s3, authenticated_client):
        initiate = _initiate_with_file(authenticated_client)
        response = authenticated_client.post(
            f"{DRAFTS_URL}{initiate['draft_id']}/remove-file/",
            {"transfer_file_id": str(_uuid.uuid4())},
            format="json",
        )
        assert response.status_code == 404

    def test_remove_rejects_other_user(self, patched_s3, authenticated_client):
        other_draft = TransferDraftFactory()
        tf = TransferFileFactory(transfer=None, draft=other_draft, upload_id="UPID")
        response = authenticated_client.post(
            f"{DRAFTS_URL}{other_draft.id}/remove-file/",
            {"transfer_file_id": str(tf.id)},
            format="json",
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestTransferFileConstraint:
    """Guarantees on TransferFile's dual FK.

    Enforced by ``transferfile_exactly_one_parent`` in models.py — exactly
    one of ``transfer`` / ``draft`` must be set. BaseModel.save calls
    ``full_clean`` before INSERT so Django raises ``ValidationError``
    ahead of the DB ever seeing an invalid row; the constraint still runs
    at the DB level too (see migration 0009), the Python-side check just
    beats it to the punch.
    """

    def test_rejects_orphan_file(self, user):
        with pytest.raises(ValidationError) as exc:
            TransferFile.objects.create(
                transfer=None,
                draft=None,
                filename="x.bin",
                size=1,
                s3_key="transfers/x/x.bin",
            )
        assert "transferfile_exactly_one_parent" in str(exc.value)

    def test_rejects_dual_parent(self, user):
        transfer = TransferFactory(owner=user)
        draft = TransferDraftFactory(owner=user)
        with pytest.raises(ValidationError) as exc:
            TransferFile.objects.create(
                transfer=transfer,
                draft=draft,
                filename="x.bin",
                size=1,
                s3_key="transfers/x/x.bin",
            )
        assert "transferfile_exactly_one_parent" in str(exc.value)


@pytest.mark.django_db
class TestCleanupAbandonedDraftsTask:
    """Cron sweep for drafts older than 24h."""

    def test_sweeps_old_drafts(self, user):
        from datetime import timedelta

        from core.tasks import cleanup_abandoned_drafts_task

        old = TransferDraftFactory(owner=user)
        # Back-date the draft beyond the 24h cutoff.
        TransferDraft.objects.filter(id=old.id).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        TransferFileFactory(
            transfer=None,
            draft=old,
            upload_id="UPID",
            s3_key="transfers/old/a.bin",
        )

        young = TransferDraftFactory(owner=user)
        TransferFileFactory(transfer=None, draft=young, upload_id="UPID2")

        with (
            patch("core.services.s3.abort_multipart_upload"),
            patch("core.services.s3.delete_object"),
        ):
            cleanup_abandoned_drafts_task()

        assert not TransferDraft.objects.filter(id=old.id).exists()
        assert TransferDraft.objects.filter(id=young.id).exists()

    def test_leaves_finalized_transfers_alone(self, user):
        """Sanity: a Transfer older than 24h must NOT be touched by this
        task — only TransferDraft rows are in scope."""
        from datetime import timedelta

        from core.tasks import cleanup_abandoned_drafts_task

        transfer = TransferFactory(owner=user)
        Transfer.objects.filter(id=transfer.id).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        TransferFileFactory(transfer=transfer, upload_completed_at=timezone.now())

        cleanup_abandoned_drafts_task()

        assert Transfer.objects.filter(id=transfer.id).exists()


@pytest.mark.django_db
class TestDraftAddFileFromDrive:
    """POST /drafts/add-file/ with ``source_url`` set — server-side Drive
    import path. The import is deferred to finalize (it needs the key), so
    add-file only records the intent: no multipart, no task, slim response
    (no upload_id/chunk_size — the client won't upload anything)."""

    DRIVE_URL = "https://fichiers.example.gouv.fr/api/v1.0/items/abc/download/"

    def _add_from_drive(self, authenticated_client, draft_id=None, **overrides):
        plaintext = overrides.pop("plaintext_size", 100)
        body = {
            "filename": "IMG.jpg",
            "plaintext_size": plaintext,
            "size": _ciphertext_size(plaintext),
            "mime_type": "image/jpeg",
            "source_url": self.DRIVE_URL,
        }
        body.update(overrides)
        if draft_id is not None:
            body["draft_id"] = str(draft_id)
        return authenticated_client.post(ADD_FILE_URL, body, format="json")

    def test_first_drop_opens_draft_defers_import(self, authenticated_client, user):
        from django.test import TestCase

        from core.enums import ScanStatus

        with (
            patch("core.api.viewsets.draft.import_drive_file_task") as mock_task,
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            response = self._add_from_drive(authenticated_client)

        assert response.status_code == 201, response.data
        # No multipart ceremony exposed to the client on the import path.
        assert "upload_id" not in response.data
        assert "chunk_size" not in response.data

        draft = TransferDraft.objects.get(id=response.data["draft_id"])
        assert draft.owner == user
        tf = draft.files.get()
        assert tf.source_url == self.DRIVE_URL
        assert tf.upload_id == ""
        assert tf.upload_completed_at is None
        # Encrypted ciphertext isn't scannable, so it's marked SKIPPED now.
        assert tf.scan_status == ScanStatus.SKIPPED

        # Import is deferred to finalize — nothing enqueued at add-file.
        mock_task.delay.assert_not_called()

    def test_rejects_file_too_large(self, authenticated_client, settings):
        settings.TRANSFER_MAX_FILE_SIZE = 1024
        response = self._add_from_drive(authenticated_client, size=2048)
        assert response.status_code == 400

    def test_mix_with_local_drop_on_same_draft(self, patched_s3, authenticated_client):
        """A draft can hold both locally-uploaded and Drive-imported files.
        The constraint is exactly one parent (draft), not uniform source."""
        local = _initiate_with_file(authenticated_client)
        imported = self._add_from_drive(
            authenticated_client, draft_id=local["draft_id"]
        )
        assert imported.status_code == 201
        assert imported.data["draft_id"] == local["draft_id"]

        draft = TransferDraft.objects.get(id=local["draft_id"])
        assert draft.files.count() == 2
        sources = {tf.source_url for tf in draft.files.all()}
        assert sources == {"", self.DRIVE_URL}


@pytest.mark.django_db
class TestDraftRetrieve:
    """GET /drafts/{id}/ — polling endpoint for per-file state."""

    def test_unauthenticated(self, api_client):
        draft = TransferDraftFactory()
        response = api_client.get(f"{DRAFTS_URL}{draft.id}/")
        assert response.status_code == 401

    def test_retrieve_returns_file_states(self, patched_s3, authenticated_client, user):
        initiate = _initiate_with_file(authenticated_client)
        authenticated_client.post(
            ADD_FILE_URL,
            {
                "draft_id": initiate["draft_id"],
                "filename": "drive.jpg",
                "plaintext_size": 50,
                "size": _ciphertext_size(50),
                "source_url": "https://drive.example/x/download/",
            },
            format="json",
        )

        response = authenticated_client.get(f"{DRAFTS_URL}{initiate['draft_id']}/")
        assert response.status_code == 200
        files_by_name = {f["filename"]: f for f in response.data["files"]}
        assert files_by_name["a.bin"]["state"] == "uploading"
        assert files_by_name["drive.jpg"]["state"] == "importing"

    def test_retrieve_rejects_other_user(self, authenticated_client):
        other = TransferDraftFactory()
        response = authenticated_client.get(f"{DRAFTS_URL}{other.id}/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestImportDriveFileTask:
    """Unit tests for the celery task ``import_drive_file_task``."""

    def _make_file(self, user, plaintext_size=100, filename="d.jpg"):
        from core.tasks import import_drive_file_task

        draft = TransferDraftFactory(owner=user, encryption_chunk_size=CHUNK)
        tf = TransferFile.objects.create(
            draft=draft,
            filename=filename,
            size=_ciphertext_size(plaintext_size),
            plaintext_size=plaintext_size,
            mime_type="image/jpeg",
            s3_key=f"transfers/placeholder/{filename}",
            source_url="https://drive.example.org/x/download/",
        )
        return tf, import_drive_file_task

    def test_idempotent_when_already_completed(self, user):
        tf, task = self._make_file(user)
        tf.upload_completed_at = timezone.now()
        tf.save(update_fields=["upload_completed_at"])

        with (
            patch("core.tasks.requests.get") as mock_get,
            patch("core.tasks.s3"),
        ):
            task(str(tf.id), VALID_KEY)

        # Never touched Drive: the row was already done.
        mock_get.assert_not_called()
        assert TransferFile.objects.filter(id=tf.id).exists()

    def test_missing_file_is_a_noop(self):
        from core.tasks import import_drive_file_task

        with patch("core.tasks.requests.get") as mock_get:
            import_drive_file_task(str(_uuid.uuid4()), VALID_KEY)
        mock_get.assert_not_called()

    def test_happy_path_encrypts_and_marks_complete(self, user):
        """One-part happy path: Drive returns the bytes, the task encrypts
        them into a fresh multipart, row is marked complete. The uploaded
        part is IV + ciphertext + tag, so it's larger than the plaintext."""
        from core.tasks import import_drive_file_task

        tf, _ = self._make_file(user, plaintext_size=12, filename="hi.txt")
        payload = b"hello-bytes!"
        assert len(payload) == 12

        class _FakeResponse:
            # A real requests.Response always exposes headers; the import task
            # reads Content-Length from them to bound the download. Empty here
            # (header absent), which exercises the mid-stream byte cap.
            headers: dict = {}

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def raise_for_status(self_inner):
                pass

            def iter_content(self_inner, chunk_size):
                yield payload

        with (
            patch("core.tasks.requests.get", return_value=_FakeResponse()),
            patch(
                "core.tasks.s3.create_multipart_upload",
                return_value="MP-1",
            ),
            patch(
                "core.tasks.s3.upload_part_bytes",
                return_value='"etag-1"',
            ) as mock_upload_part,
            patch("core.tasks.s3.complete_multipart_upload") as mock_complete,
        ):
            import_drive_file_task(str(tf.id), VALID_KEY)

        tf.refresh_from_db()
        assert tf.upload_completed_at is not None
        assert tf.upload_id == ""
        mock_upload_part.assert_called_once()
        # The body uploaded is the encrypted chunk (12 plaintext + 28 overhead).
        body = mock_upload_part.call_args.kwargs["body"]
        assert len(body) == 12 + OVERHEAD
        mock_complete.assert_called_once()

    def test_size_mismatch_marks_failed(self, user):
        """Drive returns fewer bytes than declared — the row is kept and
        marked failed (so the finalize poll surfaces it), the in-flight
        multipart aborted, the partial object deleted."""
        from core.tasks import import_drive_file_task

        tf, _ = self._make_file(user, plaintext_size=1000, filename="short.bin")

        class _FakeResponse:
            # A real requests.Response always exposes headers; the import task
            # reads Content-Length from them to bound the download. Empty here
            # (header absent), which exercises the mid-stream byte cap.
            headers: dict = {}

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def raise_for_status(self_inner):
                pass

            def iter_content(self_inner, chunk_size):
                yield b"nope"  # 4 bytes, not 1000

        with (
            patch("core.tasks.requests.get", return_value=_FakeResponse()),
            patch(
                "core.tasks.s3.create_multipart_upload",
                return_value="MP-2",
            ),
            patch(
                "core.tasks.s3.upload_part_bytes",
                return_value='"etag-1"',
            ),
            patch("core.tasks.s3.abort_multipart_upload") as mock_abort,
            patch("core.tasks.s3.delete_object") as mock_delete,
            patch("core.tasks.s3.complete_multipart_upload") as mock_complete,
        ):
            import_drive_file_task(str(tf.id), VALID_KEY)

        tf.refresh_from_db()
        assert tf.import_failed_at is not None
        assert tf.upload_completed_at is None
        mock_complete.assert_not_called()
        mock_abort.assert_called_once()
        mock_delete.assert_called_once()

    def test_oversized_content_length_rejected_before_download(self, user):
        """Drive advertises more bytes than the row declared — reject up front
        on the Content-Length header, before opening a multipart upload or
        streaming (and paying for) a single byte."""
        from core.tasks import import_drive_file_task

        tf, _ = self._make_file(user, plaintext_size=12, filename="lies.bin")

        class _FakeResponse:
            headers: dict = {"Content-Length": "999999999"}

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def raise_for_status(self_inner):
                pass

            def iter_content(self_inner, chunk_size):  # pragma: no cover
                raise AssertionError("must not stream an oversized body")

        with (
            patch("core.tasks.requests.get", return_value=_FakeResponse()),
            patch("core.tasks.s3.create_multipart_upload") as mock_create,
            patch("core.tasks.s3.complete_multipart_upload") as mock_complete,
        ):
            import_drive_file_task(str(tf.id), VALID_KEY)

        tf.refresh_from_db()
        assert tf.import_failed_at is not None
        assert tf.upload_completed_at is None
        # Rejected before any S3 work happened.
        mock_create.assert_not_called()
        mock_complete.assert_not_called()

    def test_stream_exceeding_declared_size_rejected(self, user):
        """Content-Length absent (or lying): the mid-stream cap still stops the
        download once it runs past the declared plaintext_size."""
        from core.tasks import import_drive_file_task

        tf, _ = self._make_file(user, plaintext_size=12, filename="runaway.bin")

        class _FakeResponse:
            headers: dict = {}

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def raise_for_status(self_inner):
                pass

            def iter_content(self_inner, chunk_size):
                # Far more than the declared 12 bytes.
                for _ in range(10):
                    yield b"x" * 100

        with (
            patch("core.tasks.requests.get", return_value=_FakeResponse()),
            patch("core.tasks.s3.create_multipart_upload", return_value="MP-3"),
            patch("core.tasks.s3.upload_part_bytes", return_value='"etag-1"'),
            patch("core.tasks.s3.abort_multipart_upload") as mock_abort,
            patch("core.tasks.s3.delete_object"),
            patch("core.tasks.s3.complete_multipart_upload") as mock_complete,
        ):
            import_drive_file_task(str(tf.id), VALID_KEY)

        tf.refresh_from_db()
        assert tf.import_failed_at is not None
        assert tf.upload_completed_at is None
        mock_complete.assert_not_called()
        mock_abort.assert_called_once()

    def test_drive_http_error_marks_failed(self, user):
        """Drive responds 403 / 404 — the row is kept and marked failed, no
        multipart opened (the HTTP call errors before that)."""
        import requests as _requests

        from core.tasks import import_drive_file_task

        tf, _ = self._make_file(user)

        class _FakeResponse:
            # A real requests.Response always exposes headers; the import task
            # reads Content-Length from them to bound the download. Empty here
            # (header absent), which exercises the mid-stream byte cap.
            headers: dict = {}

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def raise_for_status(self_inner):
                raise _requests.HTTPError("403 Forbidden")

            def iter_content(self_inner, chunk_size):
                return iter(())

        with (
            patch("core.tasks.requests.get", return_value=_FakeResponse()),
            patch("core.tasks.s3.create_multipart_upload") as mock_create,
            patch("core.tasks.s3.abort_multipart_upload") as mock_abort,
            patch("core.tasks.s3.delete_object"),
        ):
            import_drive_file_task(str(tf.id), VALID_KEY)

        tf.refresh_from_db()
        assert tf.import_failed_at is not None
        mock_create.assert_not_called()
        mock_abort.assert_not_called()


@pytest.mark.django_db
class TestDraftRescan:
    """POST /drafts/{id}/rescan/ — re-arm the scan on stuck files.

    The background poller gives up when the scanner is unreachable, leaving
    files PENDING with no job in flight. This endpoint (what the front's retry
    affordance calls) re-submits them without waiting for the 5-minute reaper.
    """

    @pytest.fixture(autouse=True)
    def _scan_on(self, settings):
        settings.CLAMAV_SCAN_ENABLED = True

    def _draft_with_file(self, user, scan_status, scan_error_kind=""):
        draft = TransferDraftFactory(owner=user)
        f = TransferFileFactory(
            draft=draft,
            transfer=None,
            upload_completed_at=timezone.now(),
            scan_status=scan_status,
            scan_error_kind=scan_error_kind,
        )
        return draft, f

    def _rescan(self, client, draft_id):
        return client.post(f"{DRAFTS_URL}{draft_id}/rescan/")

    def _patched(self):
        # Fire on_commit callbacks inline so the .delay assertion is testable.
        return (
            patch("core.api.viewsets.draft.submit_scan_task.delay"),
            patch(
                "core.api.viewsets.draft.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
        )

    def test_pending_file_resubmitted(self, authenticated_client, user):
        """A file stuck PENDING is re-submitted to the scanner."""
        draft, f = self._draft_with_file(user, ScanStatus.PENDING)
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == [str(f.id)]
        submit.assert_called_once_with(str(f.id))

    def test_transient_error_reset_and_resubmitted(self, authenticated_client, user):
        """A transient scan error is reset to PENDING and re-submitted."""
        draft, f = self._draft_with_file(user, ScanStatus.ERROR, "transient")
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == [str(f.id)]
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.PENDING
        assert f.scan_error_kind == ""
        submit.assert_called_once_with(str(f.id))

    def test_infected_left_untouched(self, authenticated_client, user):
        """An infected file is a hard block: never re-submitted."""
        draft, f = self._draft_with_file(user, ScanStatus.INFECTED)
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == []
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.INFECTED
        submit.assert_not_called()

    def test_file_bound_error_left_untouched(self, authenticated_client, user):
        """A file-bound (unscannable) error is a hard block: never re-submitted."""
        draft, _ = self._draft_with_file(user, ScanStatus.ERROR, "file")
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == []
        submit.assert_not_called()

    def test_clean_file_left_untouched(self, authenticated_client, user):
        """A file that already passed the scan is not re-submitted: rescan only
        re-arms stuck (PENDING) or transiently-errored files."""
        draft, f = self._draft_with_file(user, ScanStatus.CLEAN)
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == []
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.CLEAN
        submit.assert_not_called()

    def test_too_large_left_untouched(self, authenticated_client, user):
        """A scan-exempt (too large) file is not re-submitted."""
        draft, f = self._draft_with_file(user, ScanStatus.TOO_LARGE)
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == []
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.TOO_LARGE
        submit.assert_not_called()

    def test_skipped_left_untouched(self, authenticated_client, user):
        """A scan-exempt (skipped) file is not re-submitted."""
        draft, f = self._draft_with_file(user, ScanStatus.SKIPPED)
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == []
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.SKIPPED
        submit.assert_not_called()

    def test_mixed_draft_resubmits_only_eligible(self, authenticated_client, user):
        """A draft holding one file of each terminal state: only the stuck
        (PENDING) and transiently-errored files are re-armed; CLEAN, INFECTED
        and file-bound ERROR are left as-is."""
        draft = TransferDraftFactory(owner=user)

        def add(scan_status, scan_error_kind=""):
            return TransferFileFactory(
                draft=draft,
                transfer=None,
                upload_completed_at=timezone.now(),
                scan_status=scan_status,
                scan_error_kind=scan_error_kind,
            )

        pending = add(ScanStatus.PENDING)
        transient = add(ScanStatus.ERROR, "transient")
        clean = add(ScanStatus.CLEAN)
        infected = add(ScanStatus.INFECTED)
        file_err = add(ScanStatus.ERROR, "file")
        too_large = add(ScanStatus.TOO_LARGE)
        skipped = add(ScanStatus.SKIPPED)

        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)

        assert resp.status_code == 200
        eligible = {str(pending.id), str(transient.id)}
        assert set(resp.data["rescanned_file_ids"]) == eligible
        assert {c.args[0] for c in submit.call_args_list} == eligible
        assert submit.call_count == 2

        # The transient error was reset to PENDING; the hard-blocked,
        # already-clean and scan-exempt files are untouched.
        transient.refresh_from_db()
        assert transient.scan_status == ScanStatus.PENDING
        assert transient.scan_error_kind == ""
        for f, expected in (
            (clean, ScanStatus.CLEAN),
            (infected, ScanStatus.INFECTED),
            (file_err, ScanStatus.ERROR),
            (too_large, ScanStatus.TOO_LARGE),
            (skipped, ScanStatus.SKIPPED),
        ):
            f.refresh_from_db()
            assert f.scan_status == expected
        file_err.refresh_from_db()
        assert file_err.scan_error_kind == "file"

    def test_noop_when_scan_disabled(self, settings, authenticated_client, user):
        """No-op (empty result, no submit) when antivirus scanning is off."""
        settings.CLAMAV_SCAN_ENABLED = False
        draft, _ = self._draft_with_file(user, ScanStatus.PENDING)
        submit_p, commit_p = self._patched()
        with submit_p as submit, commit_p:
            resp = self._rescan(authenticated_client, draft.id)
        assert resp.status_code == 200
        assert resp.data["rescanned_file_ids"] == []
        submit.assert_not_called()

    def test_rejects_other_user(self, authenticated_client):
        """A draft owned by another user is not found (404)."""
        other_draft = TransferDraftFactory()
        TransferFileFactory(
            draft=other_draft,
            transfer=None,
            upload_completed_at=timezone.now(),
            scan_status=ScanStatus.PENDING,
        )
        resp = self._rescan(authenticated_client, other_draft.id)
        assert resp.status_code == 404
