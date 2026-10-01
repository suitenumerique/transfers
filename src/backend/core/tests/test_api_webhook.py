"""Tests for the scan-result webhook and the finalize antivirus gate.

Covers the two halves of the ``scan_error_kind`` feature:

* ``ScanResultWebhookView`` — payload → (scan_status, scan_error_kind) mapping,
  secret check, and idempotent / fail-closed behaviour.
* ``TransferDraftViewSet.finalize`` — how the gate reacts to each terminal
  scan state: a virus and an unscannable file are hard blocks; a transient
  error is reset to PENDING and re-submitted; PENDING keeps the client polling.
"""

from unittest.mock import patch

from django.conf import settings
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


def _done(kind, **verdict):
    """A completed scan whose malware axis came back as ``kind``. This is the
    whole shape the scanner sends: the flat ``malware`` aggregate it carried
    before verdicts is gone from the wire, not merely unread, and every payload
    carries the API version it is written in. Nothing here reads that stamp —
    a body this service cannot parse fails closed to ERROR like any other, and
    the sender retries the scan — but it is what the scanner actually sends."""
    return {
        "status": "done",
        "api_version": settings.SCAN_API_VERSION,
        "verdicts": {"malware": {"kind": kind, **verdict}},
    }


@pytest.mark.django_db
class TestScanResultWebhook:
    """POST /webhooks/scan-result/?file_id=&secret= — scanner callback."""

    def _file(self, **kwargs):
        kwargs.setdefault("webhook_secret", "s3cr3t")
        kwargs.setdefault("scan_status", ScanStatus.PENDING)
        return TransferFileFactory(**kwargs)

    def test_clean_payload_marks_clean(self, api_client):
        f = self._file()
        resp = _post(api_client, f.id, "s3cr3t", _done("clean"))
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.CLEAN
        assert f.scan_error_kind == ""

    def test_malware_payload_marks_infected(self, api_client):
        f = self._file()
        resp = _post(api_client, f.id, "s3cr3t", _done("malware", reason="Eicar"))
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.INFECTED
        assert f.scan_error_kind == ""

    def test_per_engine_reports_are_logged(self, api_client):
        """With several engines on a file, the log says which one said what —
        the only place that detail is kept."""
        f = self._file()
        payload = {
            **_done("malware", reason="Eicar"),
            "scanners": [
                {"scanner": "clamav", "category": "malware", "kind": "clean"},
                {
                    "scanner": "exav",
                    "category": "malware",
                    "kind": "malware",
                    "reason": "Eicar",
                },
                "garbage",
            ],
        }
        with patch("core.api.viewsets.webhook.logger") as log:
            _post(api_client, f.id, "s3cr3t", payload)
        message = log.info.call_args.args[0] % log.info.call_args.args[1:]
        assert message.endswith(" [clamav=clean, exav=malware:Eicar]")

    def test_scan_ran_but_could_not_read_the_file(self, api_client):
        """The scanner examined the file and could not read it (an encrypted
        or unreadable archive): scan-exempt with a warning — no retry, no
        detection, still downloadable."""
        f = self._file()
        payload = {
            **_done("partial", reason="PASSWORD-PROTECTED"),
            "scanners": [
                {
                    "scanner": "exav",
                    "category": "malware",
                    "kind": "partial",
                    "reason": "PASSWORD-PROTECTED",
                },
            ],
        }
        resp = _post(api_client, f.id, "s3cr3t", payload)
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.UNSCANNABLE
        assert f.scan_error_kind == ""

    def test_verdict_drives_each_terminal_state(self, api_client):
        """The engines' own words, read straight through: one mapping, no
        joining a tri-state with an error kind to work out what happened."""
        for kind, expected in (
            ("clean", ScanStatus.CLEAN),
            ("malware", ScanStatus.INFECTED),
            ("partial", ScanStatus.UNSCANNABLE),
            ("error", ScanStatus.ERROR),
        ):
            f = self._file()
            resp = _post(api_client, f.id, "s3cr3t", _done(kind))
            assert resp.status_code == 200
            f.refresh_from_db()
            assert f.scan_status == expected, kind

    def test_unknown_verdict_word_blocks_rather_than_releases(self, api_client):
        """A word this version doesn't know is not a clean bill of health. It
        is ERROR rather than INFECTED: blocked, and retryable, because the
        likelier cause is a scanner newer than this service."""
        f = self._file()
        _post(api_client, f.id, "s3cr3t", _done("quarantined"))
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "transient"

    def test_a_flagged_verdict_blocks_without_calling_it_malware(self, api_client):
        """``flagged`` is a content-policy hit. No engine on the malware axis
        produces one today, but the scanner forwards it rather than reducing
        it to ``clean``, so it must not unlock the download — and must not be
        recorded as a virus either."""
        f = self._file()
        _post(api_client, f.id, "s3cr3t", _done("flagged", reason="nsfw"))
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        # Permanent, unlike a word we have never heard of: the scan concluded,
        # so /rescan/ must not re-arm it forever.
        assert f.scan_error_kind == "file"

    @pytest.mark.parametrize("kind", [[], {}, 3, None])
    def test_a_non_string_verdict_word_fails_closed(self, api_client, kind):
        """An unhashable ``kind`` must not raise: a 500 here reads as a failed
        delivery, so the scanner would retry, dead-letter, and leave the file
        PENDING for the reaper instead of settling on a terminal status."""
        f = self._file()
        response = _post(api_client, f.id, "s3cr3t", _done(kind))
        assert response.status_code == 200
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR

    def test_job_level_error_beats_a_clean_verdict(self, api_client):
        """``status`` answers "did the job run", the verdict "what did it
        conclude": a job that failed has nothing to conclude with."""
        f = self._file()
        payload = {**_done("clean"), "status": "error", "error_kind": "transient"}
        _post(api_client, f.id, "s3cr3t", payload)
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "transient"

    def test_verdicts_without_the_malware_axis_is_blocked(self, api_client):
        """Only another axis reported: nothing decided this file's malware
        state, so there is no answer to act on."""
        f = self._file()
        payload = {"status": "done", "verdicts": {"nsfw": {"kind": "clean"}}}
        _post(api_client, f.id, "s3cr3t", payload)
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR

    def test_a_completed_scan_carrying_no_verdict_is_blocked(self, api_client):
        """A scanner too old to report verdicts answers like this. It is not
        read as clean: it blocks, which is why that scanner has to be deployed
        before this service and not after."""
        f = self._file()
        _post(api_client, f.id, "s3cr3t", {"status": "done", "malware": False})
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "transient"

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
        resp = _post(api_client, f.id, "s3cr3t", _done("clean"))
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
        resp = _post(api_client, f.id, "s3cr3t", _done("clean"))
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
        resp = _post(api_client, f.id, "wrong", _done("clean"))
        assert resp.status_code == 403
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.PENDING

    def test_unknown_file_acked(self, api_client):
        import uuid

        resp = _post(api_client, uuid.uuid4(), "s3cr3t", _done("clean"))
        assert resp.status_code == 200

    def test_missing_file_id(self, api_client):
        resp = api_client.post(
            f"{WEBHOOK_URL}?secret=s3cr3t", _done("clean"), format="json"
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
        draft = TransferDraftFactory(owner=user, encryption_chunk_size=25 * 1024 * 1024)
        f = TransferFileFactory(
            draft=draft,
            transfer=None,
            upload_completed_at=timezone.now(),
            scan_status=scan_status,
            scan_error_kind=scan_error_kind,
        )
        return draft, f

    def _finalize(self, client, draft_id):
        # Non-confidential finalize needs the key so the backend can serve it
        # to recipients; the scan gate under test runs after that check.
        return client.post(
            f"{DRAFTS_URL}{draft_id}/finalize/",
            {"encryption_key": "A" * 43},
            format="json",
        )

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

    def test_unscannable_file_finalizes_as_scan_exempt(
        self, user, authenticated_client
    ):
        # An archive the scanner could not read goes out like a too-large
        # file: not scanned, with the recipient warned.
        draft, _ = self._draft_with_file(user, ScanStatus.UNSCANNABLE)
        resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 200

    def test_file_error_blocks(self, user, authenticated_client):
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

    def test_transient_error_blocks(self, user, authenticated_client):
        # Finalize is read-only: a transient scan error is a block, not a silent
        # reset-and-retry. The file is untouched and no scan is re-submitted —
        # the user retries on the form (the /rescan/ path) instead.
        draft, f = self._draft_with_file(user, ScanStatus.ERROR, "transient")
        with patch("core.api.viewsets.draft.submit_scan_task.delay") as submit:
            resp = self._finalize(authenticated_client, draft.id)
        assert resp.status_code == 400
        assert resp.data["reason"] == "scan_error"
        assert str(f.id) in resp.data["blocked_file_ids"]
        f.refresh_from_db()
        assert f.scan_status == ScanStatus.ERROR
        assert f.scan_error_kind == "transient"
        submit.assert_not_called()

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
