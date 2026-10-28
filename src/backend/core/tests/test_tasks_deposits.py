"""Tests for the deposit tasks: the agent's notification, the depositor's
receipt, the purge of used-up challenges, and the abandoned-draft sweep on
deposit drafts."""

from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.utils import timezone

import pytest

from core.enums import ScanStatus
from core.factories import (
    DepositSpaceFactory,
    InboundTransferFactory,
    TransferFileFactory,
)
from core.models import DepositChallenge, Transfer, TransferDraft, TransferFile
from core.tasks import (
    cleanup_abandoned_drafts_task,
    purge_deposit_challenges_task,
    send_deposit_notification_task,
    send_deposit_receipt_task,
)

pytestmark = pytest.mark.django_db


def _challenge(**fields):
    fields.setdefault("deposit_space", DepositSpaceFactory())
    return DepositChallenge.objects.create(
        depositor_email="dep@example.org",
        depositor_name="Camille",
        code_hash="x",
        expires_at=timezone.now() + timedelta(minutes=10),
        **fields,
    )


def _age(model, obj, hours):
    model.objects.filter(pk=obj.pk).update(
        created_at=timezone.now() - timedelta(hours=hours)
    )


class TestNotification:
    def test_sent_once(self):
        transfer = InboundTransferFactory()
        send_deposit_notification_task(str(transfer.id))
        send_deposit_notification_task(str(transfer.id))
        assert [m.to for m in mail.outbox] == [[transfer.owner.email]]

    def test_failure_releases_the_claim(self):
        transfer = InboundTransferFactory()
        with (
            patch("core.tasks.send_deposit_notification", side_effect=OSError),
            pytest.raises(OSError),
        ):
            send_deposit_notification_task(str(transfer.id))
        transfer.refresh_from_db()
        assert transfer.notifications_completed_at is None
        send_deposit_notification_task(str(transfer.id))
        assert len(mail.outbox) == 1

    def test_warns_about_unchecked_files(self):
        transfer = InboundTransferFactory(depositor_name="<script>x</script>")
        TransferFileFactory(transfer=transfer, scan_status=ScanStatus.UNSCANNABLE)
        TransferFileFactory(transfer=transfer, scan_status=ScanStatus.CLEAN)
        send_deposit_notification_task(str(transfer.id))
        message = mail.outbox[0]
        assert "1 fichier" in message.body
        html = message.alternatives[0][0]
        assert "antivirus" in html
        # Depositor text is escaped.
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_unclaimed_send_goes_to_the_address(self):
        transfer = InboundTransferFactory(
            owner=None, deposit_space=None, inbox_email="agent@example.local"
        )
        send_deposit_notification_task(str(transfer.id))
        message = mail.outbox[0]
        assert message.to == ["agent@example.local"]
        assert "/inbox/claim?token=" in message.body
        assert "ProConnect" in message.body


@pytest.mark.parametrize(
    "task", [send_deposit_notification_task, send_deposit_receipt_task]
)
def test_deleted_deposit_sends_nothing(task):
    transfer = InboundTransferFactory()
    transfer_id = str(transfer.id)
    Transfer.objects.filter(id=transfer.id).delete()
    task(transfer_id)
    assert not mail.outbox


def test_receipt_goes_to_the_depositor():
    transfer = InboundTransferFactory(depositor_email="dep@example.org")
    TransferFileFactory(transfer=transfer, filename="plan.pdf")
    send_deposit_receipt_task(str(transfer.id))
    message = mail.outbox[0]
    assert message.to == ["dep@example.org"]
    assert "plan.pdf" in message.body
    assert transfer.deposit_space.name in message.body
    assert transfer.public_token not in message.body


class TestPurgeChallenges:
    def test_old_unused_challenges_go(self):
        old = _challenge()
        _age(DepositChallenge, old, 26)
        recent = _challenge()
        # Still counted by the default 20/day code cap.
        _age(DepositChallenge, recent, 24)
        purge_deposit_challenges_task()
        assert list(DepositChallenge.objects.all()) == [recent]

    def test_kept_as_long_as_the_code_cap_counts_them(self, settings):
        settings.THROTTLE_DEPOSIT_CODES_PER_EMAIL = (20, "week", 7 * 86400)
        challenge = _challenge()
        _age(DepositChallenge, challenge, 6 * 24)
        purge_deposit_challenges_task()
        assert DepositChallenge.objects.filter(pk=challenge.pk).exists()

    def test_kept_while_the_session_lasts(self, settings):
        settings.THROTTLE_DEPOSIT_CODES_PER_EMAIL = (20, "hour", 3600)
        challenge = _challenge()
        _age(DepositChallenge, challenge, 12)
        purge_deposit_challenges_task()
        assert DepositChallenge.objects.filter(pk=challenge.pk).exists()

    def test_challenge_holding_a_draft_stays(self):
        held = _challenge()
        TransferDraft.objects.create(deposit_challenge=held, encryption_chunk_size=1)
        _age(DepositChallenge, held, 49)
        purge_deposit_challenges_task()
        assert DepositChallenge.objects.filter(pk=held.pk).exists()

    def test_deposits_outlive_their_challenge(self):
        transfer = InboundTransferFactory()
        consumed = _challenge(deposit_space=transfer.deposit_space)
        _age(DepositChallenge, consumed, 49)
        purge_deposit_challenges_task()
        assert Transfer.objects.filter(pk=transfer.pk).exists()


def test_abandoned_deposit_draft_is_swept(patched_s3):
    challenge = _challenge()
    draft = TransferDraft.objects.create(
        deposit_challenge=challenge, encryption_chunk_size=1
    )
    TransferFileFactory(transfer=None, draft=draft)
    _age(TransferDraft, draft, 25)
    _age(DepositChallenge, challenge, 49)

    cleanup_abandoned_drafts_task()
    assert not TransferDraft.objects.exists()
    assert not TransferFile.objects.exists()
    patched_s3.delete.assert_called_once()

    purge_deposit_challenges_task()
    assert not DepositChallenge.objects.exists()
