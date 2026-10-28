"""Tests for deposit spaces and their deposits: files sent to an agent
by someone without an account, through a space's link.

The depositor's side runs without authentication: read the space, ask for
a one-time code, verify it, upload with the session token, finalize.
"""

import re
import threading
from datetime import timedelta
from unittest.mock import patch

from django.core import mail, signing
from django.db import connection
from django.utils import timezone

import pytest
from rest_framework.test import APIClient

from core.enums import ScanStatus, TransferDirection, TransferEventType, TransferStatus
from core.factories import (
    DepositSpaceFactory,
    InboundTransferFactory,
    TransferFactory,
    TransferFileFactory,
    UserFactory,
)
from core.models import DepositChallenge, Transfer, TransferDraft, TransferEvent
from core.tests.test_api_drafts import VALID_KEY, _ciphertext_size

pytestmark = pytest.mark.django_db

SPACES_URL = "/api/v1.0/deposit-spaces/"
CHALLENGES_URL = "/api/v1.0/deposit-challenges/"
DEPOSIT_DRAFTS_URL = "/api/v1.0/deposit-drafts/"
DEPOSITOR = "depositor@example.org"


def _public_url(token):
    return f"/api/v1.0/public-deposit-spaces/{token}/"


def _verify_url(challenge_id):
    return f"{CHALLENGES_URL}{challenge_id}/verify/"


def _last_code():
    """The code in the last email sent: it is in the subject."""
    return re.search(r"(\d{6})", mail.outbox[-1].subject).group(1)


def _start(client=None, **body):
    body.setdefault("depositor_name", "Camille Dupont")
    body.setdefault("depositor_email", DEPOSITOR)
    return (client or APIClient()).post(CHALLENGES_URL, body, format="json")


def _session(space=None, **body):
    """Ask for a code and verify it. Returns the session token."""
    if space is not None:
        body["space_token"] = space.link_token
    resp = _start(**body)
    assert resp.status_code == 201, resp.data
    verified = APIClient().post(
        _verify_url(resp.data["challenge_id"]), {"code": _last_code()}, format="json"
    )
    assert verified.status_code == 200, verified.data
    return verified.data["deposit_token"]


def _depositor(token):
    client = APIClient()
    client.credentials(HTTP_X_DEPOSIT_TOKEN=token)
    return client


def _add_file(client, draft_id=None, **file_body):
    body = {"filename": "a.pdf", **file_body}
    body.setdefault("plaintext_size", 100)
    body.setdefault("size", _ciphertext_size(body["plaintext_size"]))
    if draft_id is not None:
        body["draft_id"] = str(draft_id)
    return client.post(f"{DEPOSIT_DRAFTS_URL}add-file/", body, format="json")


def _upload(client, count=1, plaintext_size=100):
    """Upload ``count`` files and complete them. Returns the draft id."""
    draft_id = None
    for index in range(count):
        resp = _add_file(
            client, draft_id, filename=f"f{index}.pdf", plaintext_size=plaintext_size
        )
        assert resp.status_code == 201, resp.data
        draft_id = resp.data["draft_id"]
        done = client.post(
            f"{DEPOSIT_DRAFTS_URL}{draft_id}/complete-upload/",
            {
                "transfer_file_id": resp.data["transfer_file_id"],
                "parts": [{"PartNumber": 1, "ETag": '"etag-1"'}],
            },
            format="json",
        )
        assert done.status_code == 204, done.data
    return draft_id


def _finalize(client, draft_id, **body):
    body.setdefault("encryption_key", VALID_KEY)
    body.setdefault("title", "Pièces du dossier")
    return client.post(f"{DEPOSIT_DRAFTS_URL}{draft_id}/finalize/", body, format="json")


@pytest.fixture
def space():
    return DepositSpaceFactory(name="Urbanisme", retention_days=30)


# --- Spaces, agent side ---


class TestDepositSpaces:
    def test_create_and_list_own_spaces(self, authenticated_client, user):
        DepositSpaceFactory()  # someone else's
        resp = authenticated_client.post(
            SPACES_URL, {"name": "Etat civil", "retention_days": 7}, format="json"
        )
        assert resp.status_code == 201, resp.data
        assert resp.data["link_token"]
        assert resp.data["deposit_count"] == 0

        listed = authenticated_client.get(SPACES_URL)
        assert [s["name"] for s in listed.data["results"]] == ["Etat civil"]

    def test_open_spaces_listed_first(self, authenticated_client, user):
        DepositSpaceFactory(owner=user, name="Fermé", revoked_at=timezone.now())
        DepositSpaceFactory(owner=user, name="Ouvert")
        listed = authenticated_client.get(SPACES_URL)
        assert [s["name"] for s in listed.data["results"]] == ["Ouvert", "Fermé"]

    def test_deposit_count_skips_ended_deposits(self, authenticated_client, user):
        space = DepositSpaceFactory(owner=user)
        InboundTransferFactory(owner=user, deposit_space=space)
        InboundTransferFactory(
            owner=user, deposit_space=space, status=TransferStatus.DEACTIVATED
        )
        resp = authenticated_client.get(f"{SPACES_URL}{space.id}/")
        assert resp.data["deposit_count"] == 1

    def test_default_retention(self, authenticated_client, settings):
        resp = authenticated_client.post(SPACES_URL, {"name": "x"}, format="json")
        assert (
            resp.data["retention_days"] == settings.DEPOSIT_SPACE_DEFAULT_RETENTION_DAYS
        )

    def test_retention_must_be_a_choice(self, authenticated_client):
        resp = authenticated_client.post(
            SPACES_URL, {"name": "x", "retention_days": 365}, format="json"
        )
        assert resp.status_code == 400
        assert "retention_days" in resp.data

    def test_max_deposit_size_is_admin_only(self, authenticated_client, settings):
        resp = authenticated_client.post(
            SPACES_URL, {"name": "x", "max_deposit_size": 1}, format="json"
        )
        assert resp.status_code == 201
        assert resp.data["max_deposit_size"] == settings.DEPOSIT_MAX_TOTAL_SIZE

    def test_cannot_see_another_agents_space(self, authenticated_client):
        other = DepositSpaceFactory()
        assert authenticated_client.get(f"{SPACES_URL}{other.id}/").status_code == 404

    def test_rename_and_revoke(self, authenticated_client, user):
        space = DepositSpaceFactory(owner=user)
        renamed = authenticated_client.patch(
            f"{SPACES_URL}{space.id}/", {"name": "Nouveau"}, format="json"
        )
        assert renamed.data["name"] == "Nouveau"

        revoked = authenticated_client.post(f"{SPACES_URL}{space.id}/revoke/")
        assert revoked.status_code == 200
        assert revoked.data["revoked_at"] is not None

        again = authenticated_client.patch(
            f"{SPACES_URL}{space.id}/", {"name": "Encore"}, format="json"
        )
        assert again.status_code == 400

    def test_no_delete(self, authenticated_client, user):
        space = DepositSpaceFactory(owner=user)
        assert (
            authenticated_client.delete(f"{SPACES_URL}{space.id}/").status_code == 405
        )

    def test_create_requires_entitlement(self, authenticated_client):
        with patch(
            "core.entitlements.backends.static.StaticEntitlementsBackend.can_access",
            return_value={"result": False},
        ):
            resp = authenticated_client.post(SPACES_URL, {"name": "x"}, format="json")
        assert resp.status_code == 403

    def test_anonymous_gets_401(self, api_client):
        assert api_client.get(SPACES_URL).status_code == 401


# --- Public space page ---


class TestPublicSpace:
    def test_shows_name_and_cap_not_owner_email(self, space):
        resp = APIClient().get(_public_url(space.link_token))
        assert resp.status_code == 200
        assert resp.data["name"] == "Urbanisme"
        assert resp.data["owner_name"] == space.owner.full_name
        assert space.owner.email not in str(resp.data)

    def test_unknown(self):
        resp = APIClient().get(_public_url("nope"))
        assert resp.status_code == 404
        assert resp.data["reason"] == "not_found"

    def test_revoked(self, space):
        space.revoked_at = timezone.now()
        space.save()
        resp = APIClient().get(_public_url(space.link_token))
        assert resp.status_code == 410
        assert resp.data["reason"] == "revoked"

    def test_inactive_owner_reads_as_unknown(self, space):
        space.owner.is_active = False
        space.owner.save()
        assert APIClient().get(_public_url(space.link_token)).status_code == 404

    def test_admin_override_shows(self, space):
        space.max_deposit_size = 1234
        space.save()
        resp = APIClient().get(_public_url(space.link_token))
        assert resp.data["max_deposit_size"] == 1234


# --- One-time code ---


class TestChallenge:
    def test_code_is_mailed_to_the_depositor(self, space):
        resp = _start(space_token=space.link_token, depositor_name="<b>Spam</b>")
        assert resp.status_code == 201, resp.data
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [DEPOSITOR]
        code = _last_code()
        assert code in message.body
        # Nothing the depositor typed reaches a third party's inbox.
        assert "Spam" not in message.body
        assert "Urbanisme" in message.body
        challenge = DepositChallenge.objects.get()
        assert code not in challenge.code_hash

    def test_needs_exactly_one_target(self, space, settings):
        settings.INBOX_RECIPIENT_EMAIL_REGEX = r"[^@]+@example\.local"
        assert _start().status_code == 400
        both = _start(space_token=space.link_token, recipient_email="a@example.local")
        assert both.status_code == 400

    def test_revoked_space(self, space):
        space.revoked_at = timezone.now()
        space.save()
        assert _start(space_token=space.link_token).status_code == 410
        assert not mail.outbox

    def test_owner_without_entitlement(self, space):
        with patch(
            "core.entitlements.backends.static.StaticEntitlementsBackend.can_access",
            return_value={"result": False},
        ):
            resp = _start(space_token=space.link_token)
        assert resp.status_code == 410
        assert resp.data["reason"] == "revoked"
        assert not mail.outbox

    def test_mail_failure_drops_the_challenge(self, space):
        with patch("core.api.viewsets.deposit.send_deposit_otp", side_effect=OSError):
            resp = _start(space_token=space.link_token)
        assert resp.status_code == 503
        assert not DepositChallenge.objects.exists()

    def test_signed_in_caller_is_not_a_401(self, space, authenticated_client):
        resp = _start(authenticated_client, space_token=space.link_token)
        assert resp.status_code == 201

    def test_throttled_per_depositor_email(self, space):
        statuses = [_start(space_token=space.link_token).status_code for _ in range(6)]
        assert statuses[:5] == [201] * 5
        assert statuses[5] == 429

    def test_codes_per_address_are_capped(self, space, settings):
        settings.THROTTLE_DEPOSIT_CODES_PER_EMAIL = (2, "day", 86400)
        statuses = [_start(space_token=space.link_token).status_code for _ in range(3)]
        assert statuses == [201, 201, 429]

    def test_code_mail_never_shows_the_owner_email(self, space):
        space.owner.full_name = ""
        space.owner.save()
        _start(space_token=space.link_token)
        assert space.owner.email not in mail.outbox[-1].body
        assert "Urbanisme" in mail.outbox[-1].body

    def test_non_object_body_is_a_400(self):
        resp = APIClient().post(CHALLENGES_URL, ["x"], format="json")
        assert resp.status_code == 400

    def test_session_header_passes_cors(self, settings):
        assert "x-deposit-token" in settings.CORS_ALLOW_HEADERS

    def test_target_cap_refuses_before_mailing(self, space, settings):
        settings.THROTTLE_DEPOSITS_PER_TARGET = (1, "day", 86400)
        TransferEvent.objects.create(
            transfer_id=InboundTransferFactory(deposit_space=space).id,
            event_type=TransferEventType.DEPOSIT_RECEIVED,
            actor_type="external",
            payload={"target": f"space:{space.id}", "depositor_email": "x@y.z"},
        )
        assert _start(space_token=space.link_token).status_code == 429
        assert not mail.outbox

    def test_depositor_cap(self, space, settings):
        settings.THROTTLE_DEPOSITS_PER_DEPOSITOR = (1, "day", 86400)
        TransferEvent.objects.create(
            transfer_id=InboundTransferFactory().id,
            event_type=TransferEventType.DEPOSIT_RECEIVED,
            actor_type="external",
            payload={"target": "space:other", "depositor_email": DEPOSITOR},
        )
        assert _start(space_token=space.link_token).status_code == 429


class TestVerify:
    def _challenge(self, space):
        resp = _start(space_token=space.link_token)
        return resp.data["challenge_id"], _last_code()

    def _verify(self, challenge_id, code):
        return APIClient().post(
            _verify_url(challenge_id), {"code": code}, format="json"
        )

    @staticmethod
    def _wrong(code):
        return f"{(int(code) + 1) % 10**6:06d}"

    def test_right_code_opens_a_session(self, space):
        challenge_id, code = self._challenge(space)
        resp = self._verify(challenge_id, code)
        assert resp.status_code == 200
        assert resp.data["deposit_token"]

    def test_wrong_code_counts_down(self, space, settings):
        challenge_id, code = self._challenge(space)
        resp = self._verify(challenge_id, self._wrong(code))
        assert resp.status_code == 400
        assert resp.data["attempts_left"] == settings.DEPOSIT_OTP_MAX_ATTEMPTS - 1

    def test_attempts_run_out(self, space, settings):
        challenge_id, code = self._challenge(space)
        for _ in range(settings.DEPOSIT_OTP_MAX_ATTEMPTS - 1):
            assert self._verify(challenge_id, self._wrong(code)).status_code == 400
        assert self._verify(challenge_id, self._wrong(code)).status_code == 410
        # Even the right code is refused now.
        assert self._verify(challenge_id, code).status_code == 410

    def test_expired(self, space):
        challenge_id, code = self._challenge(space)
        DepositChallenge.objects.filter(id=challenge_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert self._verify(challenge_id, code).status_code == 410

    def test_code_works_once(self, space):
        challenge_id, code = self._challenge(space)
        assert self._verify(challenge_id, code).status_code == 200
        assert self._verify(challenge_id, code).status_code == 410

    def test_unknown_challenge(self):
        resp = APIClient().post(
            _verify_url("00000000-0000-0000-0000-000000000000"),
            {"code": "123456"},
            format="json",
        )
        assert resp.status_code == 404

    def test_code_shape(self, space):
        challenge_id, _ = self._challenge(space)
        assert self._verify(challenge_id, "12ab56").status_code == 400


# --- Upload and finalize ---


class TestDepositSession:
    def test_no_token_is_a_403_not_a_401(self, patched_s3):
        resp = _add_file(APIClient())
        assert resp.status_code == 403
        assert resp.data["reason"] == "session"

    def test_token_for_another_purpose_is_refused(self, space, patched_s3):
        challenge = DepositChallenge.objects.get(
            id=_start(space_token=space.link_token).data["challenge_id"]
        )
        challenge.verified_at = timezone.now()
        challenge.save()
        foreign = signing.TimestampSigner(salt="transfer-download-resume").sign(
            str(challenge.id)
        )
        assert _add_file(_depositor(foreign)).status_code == 403

    def test_expired_session(self, space, patched_s3, settings):
        token = _session(space)
        settings.DEPOSIT_SESSION_MAX_AGE = 0
        with patch("django.core.signing.time.time", return_value=10**10):
            assert _add_file(_depositor(token)).status_code == 403

    def test_revoked_space_closes_the_session(self, space, patched_s3):
        client = _depositor(_session(space))
        draft_id = _upload(client)
        space.revoked_at = timezone.now()
        space.save()
        resp = _finalize(client, draft_id)
        assert resp.status_code == 403
        assert resp.data["reason"] == "closed"


class TestDeposit:
    def test_depositor_text_is_one_line(self, space, patched_s3):
        client = _depositor(
            _session(space, depositor_name="Camille\r\nCliquez ici : http://x")
        )
        resp = _add_file(client, filename="a\nb.pdf")
        assert resp.status_code == 201, resp.data
        draft_id = resp.data["draft_id"]
        client.post(
            f"{DEPOSIT_DRAFTS_URL}{draft_id}/complete-upload/",
            {
                "transfer_file_id": resp.data["transfer_file_id"],
                "parts": [{"PartNumber": 1, "ETag": '"etag-1"'}],
            },
            format="json",
        )

        resp = _finalize(client, draft_id, title="Dossier\nurgent")

        assert resp.status_code == 200, resp.data
        transfer = Transfer.objects.get()
        assert transfer.depositor_name == "Camille Cliquez ici : http://x"
        assert transfer.title == "Dossier urgent"
        assert transfer.files.get().filename == "a b.pdf"

    def test_full_deposit(self, space, patched_s3, django_capture_on_commit_callbacks):
        client = _depositor(_session(space))
        draft_id = _upload(client, count=2)
        mail.outbox.clear()

        with django_capture_on_commit_callbacks(execute=True):
            resp = _finalize(client, draft_id)

        assert resp.status_code == 200, resp.data
        assert resp.data["file_count"] == 2
        assert set(resp.data) == {"title", "file_count", "total_size", "created_at"}

        transfer = Transfer.objects.get()
        assert transfer.direction == TransferDirection.INBOUND
        assert transfer.owner == space.owner
        assert transfer.deposit_space == space
        assert transfer.depositor_email == DEPOSITOR
        assert transfer.depositor_name == "Camille Dupont"
        assert transfer.encryption_key == VALID_KEY
        assert transfer.files.count() == 2
        expected = timezone.now() + timedelta(days=30)
        assert abs((transfer.expires_at - expected).total_seconds()) < 60
        assert not TransferDraft.objects.exists()

        event = TransferEvent.objects.get(event_type=TransferEventType.DEPOSIT_RECEIVED)
        assert event.payload["target"] == f"space:{space.id}"
        assert event.payload["file_count"] == 2

        recipients = sorted(m.to[0] for m in mail.outbox)
        assert recipients == sorted([space.owner.email, DEPOSITOR])
        notice = next(m for m in mail.outbox if m.to == [space.owner.email])
        assert f"/transfers/{transfer.id}" in notice.body
        receipt = next(m for m in mail.outbox if m.to == [DEPOSITOR])
        assert transfer.public_token not in receipt.body

    def test_depositor_email_comes_from_the_challenge(self, space, patched_s3):
        client = _depositor(_session(space))
        draft_id = _upload(client)
        resp = _finalize(client, draft_id, depositor_email="ceo@agency.example")
        assert resp.status_code == 200
        assert Transfer.objects.get().depositor_email == DEPOSITOR

    def test_one_deposit_per_session(self, space, patched_s3):
        client = _depositor(_session(space))
        draft_id = _upload(client)
        assert _finalize(client, draft_id).status_code == 200
        again = _add_file(client)
        assert again.status_code == 403

    def test_one_draft_per_session(self, space, patched_s3):
        client = _depositor(_session(space))
        assert _add_file(client).status_code == 201
        second = _add_file(client)
        assert second.status_code == 400

    def test_another_sessions_draft_is_invisible(self, space, patched_s3):
        draft_id = _upload(_depositor(_session(space)))
        other = _depositor(_session(space, depositor_email="other@example.org"))
        assert other.get(f"{DEPOSIT_DRAFTS_URL}{draft_id}/").status_code == 404
        assert _finalize(other, draft_id).status_code == 404

    def test_the_agent_cannot_drive_a_deposit_draft(self, space, patched_s3):
        draft_id = _upload(_depositor(_session(space)))
        agent = APIClient()
        agent.force_authenticate(space.owner)
        assert agent.get(f"/api/v1.0/drafts/{draft_id}/").status_code == 404
        assert agent.post(f"/api/v1.0/drafts/{draft_id}/abort/").status_code == 404

    def test_drive_import_refused(self, space, patched_s3):
        resp = _add_file(
            _depositor(_session(space)),
            source_url="https://drive.example.com/file/1",
        )
        assert resp.status_code == 400
        assert "source_url" in resp.data

    def test_size_cap_per_file(self, space, patched_s3):
        space.max_deposit_size = 1000
        space.save()
        resp = _add_file(_depositor(_session(space)), plaintext_size=2000)
        assert resp.status_code == 400
        assert "size" in resp.data

    def test_size_cap_across_files(self, space, patched_s3):
        space.max_deposit_size = 1000
        space.save()
        client = _depositor(_session(space))
        first = _add_file(client, plaintext_size=600)
        assert first.status_code == 201
        second = _add_file(client, first.data["draft_id"], plaintext_size=600)
        assert second.status_code == 400

    def test_key_required(self, space, patched_s3):
        client = _depositor(_session(space))
        draft_id = _upload(client)
        resp = client.post(
            f"{DEPOSIT_DRAFTS_URL}{draft_id}/finalize/", {"title": "x"}, format="json"
        )
        assert resp.status_code == 400
        assert "encryption_key" in resp.data

    def test_entitlement_checked_on_the_owner(self, space, patched_s3):
        client = _depositor(_session(space))
        draft_id = _upload(client)
        with patch(
            "core.entitlements.backends.static.StaticEntitlementsBackend.can_access",
            return_value={"result": False},
        ):
            resp = _finalize(client, draft_id)
        assert resp.status_code == 403
        assert resp.data["reason"] == "closed"

    def test_target_cap_at_finalize(self, space, patched_s3, settings):
        first = _depositor(_session(space))
        second = _depositor(_session(space, depositor_email="two@example.org"))
        first_draft, second_draft = _upload(first), _upload(second)
        settings.THROTTLE_DEPOSITS_PER_TARGET = (1, "day", 86400)
        assert _finalize(first, first_draft).status_code == 200
        assert _finalize(second, second_draft).status_code == 429


class TestDepositScan:
    @pytest.fixture(autouse=True)
    def _scan_on(self, settings):
        settings.SCAN_ENABLED = True

    def _uploaded(self, space):
        client = _depositor(_session(space))
        draft_id = _upload(client)
        with patch("core.tasks.submit_scan_task.send"):
            pending = _finalize(client, draft_id)
        assert pending.status_code == 202
        return client, draft_id

    @pytest.mark.parametrize(
        "status,error_kind,reason",
        [
            (ScanStatus.INFECTED, "", "scan_blocked"),
            (ScanStatus.ERROR, "file", "scan_file_error"),
            (ScanStatus.ERROR, "", "scan_error"),
        ],
    )
    def test_blocking_verdicts_refuse_the_deposit(
        self, space, patched_s3, status, error_kind, reason
    ):
        client, draft_id = self._uploaded(space)
        TransferDraft.objects.get(id=draft_id).files.update(
            scan_status=status, scan_error_kind=error_kind
        )
        resp = _finalize(client, draft_id)
        assert resp.status_code == 400
        assert resp.data["reason"] == reason
        assert not Transfer.objects.exists()

    @pytest.mark.parametrize(
        "status", [ScanStatus.UNSCANNABLE, ScanStatus.TOO_LARGE, ScanStatus.CLEAN]
    )
    def test_unchecked_files_go_through(self, space, patched_s3, status):
        client, draft_id = self._uploaded(space)
        TransferDraft.objects.get(id=draft_id).files.update(scan_status=status)
        assert _finalize(client, draft_id).status_code == 200

    def test_scanner_reads_the_parked_key(self, space, patched_s3):
        _client, draft_id = self._uploaded(space)
        assert TransferDraft.objects.get(id=draft_id).encryption_key == VALID_KEY


# --- The agent reading deposits ---


class TestInboundAccess:
    def test_public_token_is_no_capability(self, patched_s3):
        transfer = InboundTransferFactory()
        tf = TransferFileFactory(
            transfer=transfer,
            upload_completed_at=timezone.now(),
            scan_status=ScanStatus.CLEAN,
        )
        url = f"/api/v1.0/downloads/{transfer.public_token}/"
        file_url = f"{url}files/{tf.id}/download/"

        assert APIClient().get(url).status_code == 404
        assert APIClient().get(file_url).status_code == 404

        stranger = APIClient()
        stranger.force_authenticate(UserFactory())
        assert stranger.get(url).status_code == 404
        assert stranger.get(file_url).status_code == 404

        owner = APIClient()
        owner.force_authenticate(transfer.owner)
        resp = owner.get(url)
        assert resp.status_code == 200
        assert resp.data["encryption_key"] == transfer.encryption_key
        assert resp.data["direction"] == TransferDirection.INBOUND
        with patch(
            "core.api.viewsets.download.sign_download_url", return_value="https://s3/x"
        ):
            assert owner.get(file_url).status_code == 302

    def test_unclaimed_send_is_nobodys(self):
        transfer = InboundTransferFactory(
            owner=None, deposit_space=None, inbox_email="agent@example.local"
        )
        agent = APIClient()
        agent.force_authenticate(UserFactory(email="agent@example.local"))
        assert (
            agent.get(f"/api/v1.0/downloads/{transfer.public_token}/").status_code
            == 404
        )

    def test_outbound_links_still_public(self):
        transfer = TransferFactory()
        assert (
            APIClient().get(f"/api/v1.0/downloads/{transfer.public_token}/").status_code
            == 200
        )


class TestTransferListDirection:
    def test_sent_list_excludes_deposits(self, authenticated_client, user):
        sent = TransferFactory(owner=user)
        InboundTransferFactory(owner=user)
        resp = authenticated_client.get("/api/v1.0/transfers/")
        assert [t["id"] for t in resp.data["results"]] == [str(sent.id)]

    def test_inbound_filters(self, authenticated_client, user):
        space = DepositSpaceFactory(owner=user)
        in_space = InboundTransferFactory(owner=user, deposit_space=space)
        other_space = InboundTransferFactory(owner=user)
        inbox = InboundTransferFactory(
            owner=user, deposit_space=None, inbox_email="agent@example.local"
        )

        def ids(query):
            resp = authenticated_client.get(f"/api/v1.0/transfers/?{query}")
            assert resp.status_code == 200
            return {t["id"] for t in resp.data["results"]}

        assert ids("direction=inbound") == {
            str(in_space.id),
            str(other_space.id),
            str(inbox.id),
        }
        assert ids(f"direction=inbound&deposit_space={space.id}") == {str(in_space.id)}
        assert ids("direction=inbound&inbox=true") == {str(inbox.id)}
        assert ids("direction=inbound&deposit_space=not-a-uuid") == set()

    def test_deposit_of_a_gone_space_is_not_an_anonymous_send(
        self, authenticated_client, user
    ):
        InboundTransferFactory(owner=user, deposit_space=None, inbox_email="")
        resp = authenticated_client.get(
            "/api/v1.0/transfers/?direction=inbound&inbox=true"
        )
        assert resp.data["results"] == []

    def test_detail_shows_the_depositor(self, authenticated_client, user):
        transfer = InboundTransferFactory(owner=user, depositor_name="Camille")
        resp = authenticated_client.get(f"/api/v1.0/transfers/{transfer.id}/")
        assert resp.data["direction"] == "inbound"
        assert resp.data["depositor_name"] == "Camille"

    def test_space_counts_its_deposits(self, authenticated_client, user):
        space = DepositSpaceFactory(owner=user)
        InboundTransferFactory(owner=user, deposit_space=space)
        resp = authenticated_client.get(f"{SPACES_URL}{space.id}/")
        assert resp.data["deposit_count"] == 1


def test_config_exposes_deposit_settings(settings):
    settings.INBOX_RECIPIENT_EMAIL_REGEX = ""
    data = APIClient().get("/api/v1.0/config/").data
    assert data["DEPOSIT_MAX_TOTAL_SIZE"] == settings.DEPOSIT_MAX_TOTAL_SIZE
    assert (
        data["DEPOSIT_SPACE_RETENTION_CHOICES"]
        == settings.DEPOSIT_SPACE_RETENTION_CHOICES
    )
    assert data["INBOX_ENABLED"] is False


# --- Races ---


def _race(*requests):
    """Run the requests at the same moment, each in its own thread and
    database connection. Returns their status codes, sorted."""
    start = threading.Barrier(len(requests))
    codes, errors = [], []

    def run(request):
        try:
            # Bounded: a thread failing before the barrier breaks it instead
            # of leaving the others waiting forever.
            start.wait(timeout=10)
            codes.append(request().status_code)
        except Exception as exc:
            errors.append(exc)
            start.abort()
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(r,)) for r in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    return sorted(codes)


@pytest.mark.django_db(transaction=True)
def test_parallel_verifies_open_one_session():
    space = DepositSpaceFactory()
    resp = _start(space_token=space.link_token)
    url, code = _verify_url(resp.data["challenge_id"]), _last_code()

    def verify():
        return APIClient().post(url, {"code": code}, format="json")

    assert _race(verify, verify) == [200, 410]


@pytest.mark.django_db(transaction=True)
def test_parallel_finalizes_make_one_deposit(patched_s3):
    space = DepositSpaceFactory()
    token = _session(space)
    draft_id = _upload(_depositor(token))

    def finalize():
        return _finalize(_depositor(token), draft_id)

    with (
        patch("core.tasks.send_deposit_notification_task.send"),
        patch("core.tasks.send_deposit_receipt_task.send"),
    ):
        codes = _race(finalize, finalize)
    # The loser either waited on the draft lock, then found the draft gone
    # (404), or came in after the commit with a consumed session (403).
    assert codes in ([200, 403], [200, 404]), codes
    assert Transfer.objects.count() == 1
