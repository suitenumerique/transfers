"""Tests for inbox sends: files sent straight to an agent's
email, allowed by ``INBOX_RECIPIENT_EMAIL_REGEX``, and the claim that
attaches them to an account."""

import re
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.utils import timezone

import pytest
from rest_framework.test import APIClient

from core.enums import TransferDirection, TransferEventType, TransferStatus
from core.factories import InboundTransferFactory, TransferFactory, UserFactory
from core.models import Transfer, TransferEvent
from core.services import deposits
from core.tests.test_api_deposits import (
    DEPOSITOR,
    _depositor,
    _finalize,
    _session,
    _start,
    _upload,
)

pytestmark = pytest.mark.django_db

AGENT = "agent@example.local"
CLAIM_URL = "/api/v1.0/inbox/claim/"


@pytest.fixture(autouse=True)
def _inbound_on(settings):
    settings.INBOX_RECIPIENT_EMAIL_REGEX = r"[^@\s]+@example\.local"


def _send(patched_s3, capture, recipient=AGENT):
    client = _depositor(_session(recipient_email=recipient))
    draft_id = _upload(client)
    mail.outbox.clear()
    with capture(execute=True):
        resp = _finalize(client, draft_id)
    assert resp.status_code == 200, resp.data
    return Transfer.objects.filter(inbox_email=recipient.lower()).latest("created_at")


def _claim_token():
    """The claim link's token, from the notification just sent."""
    notice = next(m for m in mail.outbox if m.to == [AGENT])
    return re.search(r"/inbox/claim\?token=(\S+)", notice.body).group(1)


def _as(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class TestTarget:
    @pytest.mark.parametrize(
        "email", ["agent@example.local", "Agent@Example.LOCAL", "a.b+c@example.local"]
    )
    def test_matching_address(self, email):
        assert _start(recipient_email=email).status_code == 201

    @pytest.mark.parametrize(
        "email",
        ["agent@example.org", "agent@example.local.evil.org", "x@sub.example.org"],
    )
    def test_the_whole_address_must_match(self, email):
        resp = _start(recipient_email=email)
        assert resp.status_code == 400
        assert resp.data["reason"] == "recipient_not_allowed"
        assert not mail.outbox

    def test_disabled_when_no_pattern(self, settings):
        settings.INBOX_RECIPIENT_EMAIL_REGEX = ""
        assert _start(recipient_email=AGENT).status_code == 404

    def test_same_answer_with_or_without_an_account(self):
        without = _start(recipient_email="nobody@example.local")
        UserFactory(email="somebody@example.local")
        with_account = _start(
            recipient_email="somebody@example.local", depositor_email="b@example.org"
        )
        assert without.status_code == with_account.status_code == 201
        assert set(without.data) == set(with_account.data)

    def test_code_mail_names_the_target(self):
        _start(recipient_email=AGENT)
        assert AGENT in mail.outbox[-1].body
        assert mail.outbox[-1].to == [DEPOSITOR]


class TestSend:
    def test_unclaimed_send_mails_a_claim_link(
        self, patched_s3, django_capture_on_commit_callbacks
    ):
        transfer = _send(patched_s3, django_capture_on_commit_callbacks)
        assert transfer.direction == TransferDirection.INBOUND
        assert transfer.owner is None
        assert transfer.deposit_space is None
        assert _claim_token()

    def test_identity_email_alone_does_not_attach(
        self, patched_s3, django_capture_on_commit_callbacks
    ):
        UserFactory(email=AGENT)
        transfer = _send(patched_s3, django_capture_on_commit_callbacks)
        assert transfer.owner is None

    def test_attaches_to_who_already_claimed_that_address(
        self, patched_s3, django_capture_on_commit_callbacks
    ):
        agent = UserFactory(email=AGENT, inbox_claimed_email=AGENT)
        transfer = _send(patched_s3, django_capture_on_commit_callbacks)
        assert transfer.owner == agent
        notice = next(m for m in mail.outbox if m.to == [AGENT])
        assert "/inbox/claim" not in notice.body
        assert f"/transfers/{transfer.id}" in notice.body

    def test_ambiguous_owner_does_not_attach(
        self, patched_s3, django_capture_on_commit_callbacks
    ):
        UserFactory(email=AGENT, inbox_claimed_email=AGENT)
        UserFactory(email=AGENT.upper(), inbox_claimed_email=AGENT)
        transfer = _send(patched_s3, django_capture_on_commit_callbacks)
        assert transfer.owner is None

    def test_target_cap(self, patched_s3, settings):
        settings.THROTTLE_DEPOSITS_PER_TARGET = (1, "day", 86400)
        client = _depositor(_session(recipient_email=AGENT))
        assert _finalize(client, _upload(client)).status_code == 200
        resp = _start(recipient_email=AGENT, depositor_email="other@example.org")
        assert resp.status_code == 429

    def test_pattern_change_closes_open_sessions(self, patched_s3, settings):
        client = _depositor(_session(recipient_email=AGENT))
        draft_id = _upload(client)
        settings.INBOX_RECIPIENT_EMAIL_REGEX = r"[^@]+@other\.example"
        assert _finalize(client, draft_id).status_code == 403


class TestClaim:
    @pytest.fixture
    def sent(self, patched_s3, django_capture_on_commit_callbacks):
        transfer = _send(patched_s3, django_capture_on_commit_callbacks)
        return transfer, _claim_token()

    def test_claim(self, sent):
        transfer, token = sent
        agent = UserFactory(email=AGENT)
        resp = _as(agent).post(CLAIM_URL, {"token": token}, format="json")
        assert resp.status_code == 200
        assert resp.data["id"] == str(transfer.id)
        transfer.refresh_from_db()
        agent.refresh_from_db()
        assert transfer.owner == agent
        assert agent.inbox_claimed_email == AGENT
        assert TransferEvent.objects.filter(
            transfer_id=transfer.id, event_type=TransferEventType.INBOUND_CLAIMED
        ).exists()

    def test_claim_takes_every_pending_send_to_the_address(self, sent):
        transfer, token = sent
        sibling = InboundTransferFactory(
            owner=None, deposit_space=None, inbox_email=AGENT
        )
        foreign = InboundTransferFactory(
            owner=None, deposit_space=None, inbox_email="other@example.local"
        )
        agent = UserFactory(email=AGENT)
        _as(agent).post(CLAIM_URL, {"token": token}, format="json")
        sibling.refresh_from_db()
        foreign.refresh_from_db()
        assert sibling.owner == agent
        assert foreign.owner is None

    def test_identity_email_is_case_insensitive(self, sent):
        _transfer, token = sent
        agent = UserFactory(email=AGENT.upper())
        assert (
            _as(agent).post(CLAIM_URL, {"token": token}, format="json").status_code
            == 200
        )

    def test_another_address_cannot_claim(self, sent):
        transfer, token = sent
        resp = _as(UserFactory(email="thief@example.local")).post(
            CLAIM_URL, {"token": token}, format="json"
        )
        assert resp.status_code == 403
        assert resp.data["reason"] == "wrong_account"
        transfer.refresh_from_db()
        assert transfer.owner is None

    def test_forged_token(self):
        transfer = InboundTransferFactory(
            owner=None, deposit_space=None, inbox_email=AGENT
        )
        resp = _as(UserFactory(email=AGENT)).post(
            CLAIM_URL, {"token": f"{transfer.id}:forged"}, format="json"
        )
        assert resp.status_code == 400

    def test_malformed_body(self):
        resp = _as(UserFactory(email=AGENT)).post(CLAIM_URL, [], format="json")
        assert resp.status_code == 400

    def test_expired_pending_sends_are_left(self, sent):
        _transfer, token = sent
        stale = InboundTransferFactory(
            owner=None,
            deposit_space=None,
            inbox_email=AGENT,
            expires_at=timezone.now() - timedelta(days=1),
        )
        _as(UserFactory(email=AGENT)).post(CLAIM_URL, {"token": token}, format="json")
        stale.refresh_from_db()
        assert stale.owner is None

    def test_already_claimed_by_someone_else(self, sent):
        transfer, token = sent
        first = UserFactory(email=AGENT)
        _as(first).post(CLAIM_URL, {"token": token}, format="json")
        second = UserFactory(email=AGENT.upper())
        resp = _as(second).post(CLAIM_URL, {"token": token}, format="json")
        assert resp.status_code == 404

    def test_claiming_twice_is_fine(self, sent):
        _transfer, token = sent
        agent = UserFactory(email=AGENT)
        _as(agent).post(CLAIM_URL, {"token": token}, format="json")
        assert (
            _as(agent).post(CLAIM_URL, {"token": token}, format="json").status_code
            == 200
        )

    def test_expired(self, sent):
        transfer, token = sent
        Transfer.objects.filter(id=transfer.id).update(
            status=TransferStatus.PENDING_FILE_DELETION
        )
        resp = _as(UserFactory(email=AGENT)).post(
            CLAIM_URL, {"token": token}, format="json"
        )
        assert resp.status_code == 410

    def test_signed_out(self, sent):
        _transfer, token = sent
        assert (
            APIClient().post(CLAIM_URL, {"token": token}, format="json").status_code
            == 401
        )

    def test_outbound_transfer_cannot_be_claimed(self, user):
        transfer = TransferFactory(owner=None)
        token = deposits.sign_claim(transfer)
        resp = _as(UserFactory(email=AGENT)).post(
            CLAIM_URL, {"token": token}, format="json"
        )
        assert resp.status_code == 404

    def test_inbox_lists_claimed_sends(self, sent):
        transfer, token = sent
        agent = UserFactory(email=AGENT)
        client = _as(agent)
        client.post(CLAIM_URL, {"token": token}, format="json")
        resp = client.get("/api/v1.0/transfers/?direction=inbound&inbox=true")
        assert [t["id"] for t in resp.data["results"]] == [str(transfer.id)]
        assert resp.data["results"][0]["depositor_email"] == DEPOSITOR


def test_claim_token_ages_out(settings):
    transfer = InboundTransferFactory(owner=None, deposit_space=None, inbox_email=AGENT)
    token = deposits.sign_claim(transfer)
    assert deposits.load_claim(token) == str(transfer.id)
    later = timezone.now().timestamp() + (settings.INBOX_RETENTION_DAYS + 2) * 86400
    with patch("django.core.signing.time.time", return_value=later):
        assert deposits.load_claim(token) is None
