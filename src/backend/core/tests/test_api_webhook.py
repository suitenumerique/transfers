"""Tests for the scan-result webhook and the finalize antivirus gate.

Covers the two halves of the ``scan_error_kind`` feature:

* ``ScanResultWebhookView`` — payload → (scan_status, scan_error_kind) mapping,
  secret check, and idempotent / fail-closed behaviour.
* ``TransferDraftViewSet.finalize`` — how the gate reacts to each terminal
  scan state: a virus and an unscannable file are hard blocks; a transient
  error is reset to PENDING and re-submitted; PENDING keeps the client polling.
"""

from unittest.mock import patch

from django.utils import timezone

import pytest

from core.enums import ScanStatus
from core.factories import TransferDraftFactory, TransferFileFactory

WEBHOOK_URL = "/api/v1.0/webhooks/scan-result/"
DRAFTS_URL = "/api/v1.0/drafts/"


def _post(api_client, file_id, secret, body):
    return api_client.post(
        f"{WEBHOOK_URL}?file_id={file_id}&secret={secret}",
        body,
        format="json",
    )


@pytest.mark.django_db
class TestScanResultWebhook:
    """POST /webhooks/scan-result/?file_id=&secret= — scanner callback."""

    def _file(self, **kwargs):
        kwargs.setdefault("webhook_secret", "s3cr3t")
        kwargs.setdefault("scan_status", ScanStatus.PENDING)
        return TransferFileFactory(**kwargs)

    def test_clean_payload_marks_clean(self, api_client):
        f = self._file()
        resp = _post(api_client, f.id, "s3cr3t", {"status": "done", "malware": False})
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.CLEAN
        assert f.scan_error_kind == ""

    def test_malware_payload_marks_infected(self, api_client):
        f = self._file()
        resp = _post(
            api_client, f.id, "s3cr3t", {"status": "done", "malware": True}
        )
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.INFECTED
        assert f.scan_error_kind == ""

    def test_error_file_kind(self, api_client):
        f = self._file()
        resp = _post(
            api_client, f.id, "s3cr3t", {"status": "error", "error_kind": "file"}
        )
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "file"

    def test_error_transient_kind(self, api_client):
        f = self._file()
        resp = _post(
            api_client,
            f.id,
            "s3cr3t",
            {"status": "error", "error_kind": "transient"},
        )
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "transient"

    def test_error_without_kind_defaults_transient(self, api_client):
        f = self._file()
        resp = _post(api_client, f.id, "s3cr3t", {"status": "error"})
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "transient"

    def test_error_with_bogus_kind_defaults_transient(self, api_client):
        f = self._file()
        resp = _post(
            api_client, f.id, "s3cr3t", {"status": "error", "error_kind": "nonsense"}
        )
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_error_kind == "transient"

    def test_terminal_state_not_overwritten(self, api_client):
        # Once a file reaches a terminal verdict it is no longer PENDING, so a
        # stale or duplicate callback must not move it (fail closed).
        f = self._file(scan_status=ScanStatus.INFECTED)
        resp = _post(api_client, f.id, "s3cr3t", {"status": "done", "malware": False})
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.INFECTED

    def test_duplicate_callback_cannot_flip_clean(self, api_client):
        # A second scan job (e.g. a reaper re-submit after a slow webhook) that
        # reports an error must not unset an already-CLEAN file.
        f = self._file(scan_status=ScanStatus.CLEAN)
        resp = _post(
            api_client,
            f.id,
            "s3cr3t",
            {"status": "error", "error_kind": "transient"},
        )
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.CLEAN
        assert f.scan_error_kind == ""

    def test_error_terminal_state_not_overwritten(self, api_client):
        # ERROR is terminal too: a stale or duplicate clean callback must not
        # flip an already-errored file to CLEAN.
        f = self._file(scan_status=ScanStatus.ERROR, scan_error_kind="file")
        resp = _post(api_client, f.id, "s3cr3t", {"status": "done", "malware": False})
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "file"

    def test_malformed_body_fails_closed(self, api_client):
        # A non-dict body must not unlock a download: it maps to ERROR.
        f = self._file()
        resp = _post(api_client, f.id, "s3cr3t", ["not", "a", "dict"])
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR

    def test_bad_secret_rejected(self, api_client):
        f = self._file()
        resp = _post(api_client, f.id, "wrong", {"status": "done", "malware": False})
        assert resp.status_code == 403
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.PENDING

    def test_unknown_file_acked(self, api_client):
        import uuid

        resp = _post(api_client, uuid.uuid4(), "s3cr3t", {"malware": False})
        assert resp.status_code == 200

    def test_missing_file_id(self, api_client):
        resp = api_client.post(
            f"{WEBHOOK_URL}?secret=s3cr3t", {"malware": False}, format="json"
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestFinalizeScanGate:
    """POST /drafts/{id}/finalize/ — the antivirus gate, scan enabled.

    State is built directly with factories (one uploaded draft file per case)
    so each terminal scan_status / scan_error_kind can be exercised in
    isolation without the upload round-trip.
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

    def _finalize(self, client, draft_id):
        return client.post(f"{DRAFTS_URL}{draft_id}/finalize/", {}, format="json")

    def test_clean_finalizes(self, user, authenticated_client):
        draft, _ = self._draft_with_file(user, ScanStatus.CLEAN)
        resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 200

    def test_infected_blocks(self, user, authenticated_client):
        # A hard block is a DRF ValidationError → 400; the client keys off the
        # ``reason``, not the status code.
        draft, f = self._draft_with_file(user, ScanStatus.INFECTED)
        resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 400
        assert resp.data["reason"] == "scan_blocked"
        assert str(f.id) in resp.data["blocked_file_ids"]

    def test_unscannable_blocks(self, user, authenticated_client):
        draft, f = self._draft_with_file(user, ScanStatus.ERROR, "file")
        resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 400
        assert resp.data["reason"] == "scan_file_error"
        assert str(f.id) in resp.data["blocked_file_ids"]

    def test_pending_keeps_polling(self, user, authenticated_client):
        draft, f = self._draft_with_file(user, ScanStatus.PENDING)
        resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 202
        assert resp.data["reason"] == "scan_pending"
        assert str(f.id) in resp.data["pending_file_ids"]

    def test_transient_error_resets_and_resubmits(self, user, authenticated_client):
        draft, f = self._draft_with_file(user, ScanStatus.ERROR, "transient")
        with patch(
            "core.api.viewsets.draft.submit_scan_task.delay"
        ) as submit, patch(
            "core.api.viewsets.draft.transaction.on_commit",
            side_effect=lambda fn: fn(),
        ):
            resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 202
        assert resp.data["reason"] == "scan_pending"
        # The transient error is wiped and the file goes back to PENDING and is
        # re-submitted to the scanner.
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.PENDING
        assert f.scan_error_kind == ""
        submit.assert_called_once_with(str(f.id))

    def test_infected_wins_over_unscannable(self, user, authenticated_client):
        # Two terminal hard blocks at once: a virus outranks an unscannable
        # file in the reported reason.
        draft = TransferDraftFactory(owner=user)
        TransferFileFactory(
            draft=draft,
            transfer=None,
            upload_completed_at=timezone.now(),
            scan_status=ScanStatus.INFECTED,
        )
        TransferFileFactory(
            draft=draft,
            transfer=None,
            upload_completed_at=timezone.now(),
            scan_status=ScanStatus.ERROR,
            scan_error_kind="file",
        )
        resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 400
        assert resp.data["reason"] == "scan_blocked"
