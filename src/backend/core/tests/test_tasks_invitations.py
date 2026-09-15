"""send_recipient_invitations_task: one SMTP session per batch, per-recipient
failure isolation, and the completion stamp the frontend polls on."""

from unittest.mock import MagicMock, patch

from django.core import mail
from django.utils import timezone

import pytest

from core.enums import ActorType, SharingMode, TransferEventType
from core.factories import TransferFactory, TransferFileFactory
from core.models import TransferEvent, TransferRecipient
from core.tasks import send_download_receipt_task, send_recipient_invitations_task

pytestmark = pytest.mark.django_db


def _transfer_with_recipients(count):
    transfer = TransferFactory(sharing_mode=SharingMode.EMAIL)
    for i in range(count):
        TransferRecipient.objects.create(transfer=transfer, email=f"r{i}@example.org")
    return transfer


def test_batch_shares_one_mail_connection():
    """A 5-recipient transfer must cost one open/close, not five: the
    sender's screen waits on this task, and each SMTP handshake is
    hundreds of milliseconds against a real relay."""
    transfer = _transfer_with_recipients(5)
    connection = MagicMock()

    with patch("core.tasks.get_connection", return_value=connection) as get_conn:
        send_recipient_invitations_task(str(transfer.id))

    assert get_conn.call_count == 1
    assert connection.open.call_count == 1
    assert connection.send_messages.call_count == 5
    assert connection.close.call_count == 1
    # Every message went through the shared session, not a fresh one.
    for call in connection.send_messages.call_args_list:
        (messages,) = call.args
        assert [m.connection for m in messages] == [connection]

    transfer.refresh_from_db()
    assert transfer.notifications_completed_at is not None
    assert not transfer.recipients.filter(email_sent_at__isnull=True).exists()
    assert (
        TransferEvent.objects.filter(
            transfer_id=transfer.id, event_type=TransferEventType.EMAIL_SENT
        ).count()
        == 5
    )


def test_one_failed_send_does_not_sink_the_batch():
    """A relay hiccup on one recipient leaves that one retryable
    (email_sent_at NULL) and the rest sent; the session is reset after the
    failure so the next send doesn't ride a dead socket; the completion
    stamp still lands so the frontend leaves its polling state."""
    transfer = _transfer_with_recipients(3)
    connection = MagicMock()
    connection.send_messages.side_effect = [1, OSError("relay dropped"), 1]

    with patch("core.tasks.get_connection", return_value=connection):
        send_recipient_invitations_task(str(transfer.id))

    sent = sorted(
        transfer.recipients.filter(email_sent_at__isnull=False).values_list(
            "email", flat=True
        )
    )
    assert sent == ["r0@example.org", "r2@example.org"]
    assert transfer.recipients.get(email="r1@example.org").email_sent_at is None
    # One close after the failure, one in the final cleanup.
    assert connection.close.call_count == 2
    transfer.refresh_from_db()
    assert transfer.notifications_completed_at is not None


def test_relay_down_at_open_still_walks_every_recipient_and_completes():
    """If even the initial open() fails, nothing is sent but every
    recipient stays retryable and the task still stamps completion —
    otherwise the sender's screen would poll forever."""
    transfer = _transfer_with_recipients(2)
    connection = MagicMock()
    connection.open.side_effect = OSError("connection refused")
    connection.send_messages.side_effect = OSError("connection refused")

    with patch("core.tasks.get_connection", return_value=connection):
        send_recipient_invitations_task(str(transfer.id))

    assert connection.send_messages.call_count == 2
    assert not transfer.recipients.filter(email_sent_at__isnull=False).exists()
    transfer.refresh_from_db()
    assert transfer.notifications_completed_at is not None


def test_download_receipt_is_sent_once_to_the_owner():
    """The stamp is claimed before sending, so a second enqueue for the same
    recipient (parallel last-file downloads) is a no-op."""
    transfer = TransferFactory(sharing_mode=SharingMode.EMAIL, notify_on_download=True)
    recipient = TransferRecipient.objects.create(
        transfer=transfer, email="dest@example.org"
    )

    send_download_receipt_task(str(transfer.id), str(recipient.id))
    send_download_receipt_task(str(transfer.id), str(recipient.id))

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [transfer.owner.email]
    assert "dest@example.org" in message.subject
    assert f"/transfers/{transfer.id}" in message.body
    recipient.refresh_from_db()
    assert recipient.download_notified_at is not None


def test_download_receipt_failure_releases_both_stamps_and_retries():
    """A relay error must not burn the recipient's single receipt, nor
    pass as a successful task: both claims go back to NULL (so a later
    download can re-arm) and the task retries. Called directly, Celery's
    ``retry`` re-raises the original error instead of scheduling."""
    transfer = TransferFactory(sharing_mode=SharingMode.EMAIL, notify_on_download=True)
    recipient = TransferRecipient.objects.create(
        transfer=transfer,
        email="dest@example.org",
        delayed_receipt_armed_at=timezone.now(),
    )

    with (
        patch("core.tasks.send_download_receipt", side_effect=OSError("relay")),
        pytest.raises(OSError),
    ):
        send_download_receipt_task(str(transfer.id), str(recipient.id))

    recipient.refresh_from_db()
    assert recipient.download_notified_at is None
    assert recipient.delayed_receipt_armed_at is None


def test_download_receipt_reports_partial_state():
    """Fired by the delayed trigger for a recipient who stopped partway: the
    subject and body say n of N and which files were taken."""
    transfer = TransferFactory(sharing_mode=SharingMode.EMAIL, notify_on_download=True)
    taken = TransferFileFactory(transfer=transfer, filename="pris.pdf")
    TransferFileFactory(transfer=transfer, filename="laisse.pdf")
    recipient = TransferRecipient.objects.create(
        transfer=transfer, email="dest@example.org"
    )
    TransferEvent.objects.create(
        transfer_id=transfer.id,
        recipient_id=recipient.id,
        event_type=TransferEventType.FILE_DOWNLOADED,
        actor_type=ActorType.EXTERNAL,
        payload={"file_id": str(taken.id)},
    )

    send_download_receipt_task(str(transfer.id), str(recipient.id))

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == "dest@example.org a téléchargé 1 fichier sur 2"
    assert "pris.pdf" in message.body and "laisse.pdf" in message.body
    assert "non téléchargé" in message.body


def test_download_receipt_html_renders_no_template_comment():
    """``{# … #}`` is single-line only in Django: a comment spanning two
    lines is emitted verbatim into the email body."""
    transfer = TransferFactory(sharing_mode=SharingMode.EMAIL, notify_on_download=True)
    TransferFileFactory(transfer=transfer)
    recipient = TransferRecipient.objects.create(
        transfer=transfer, email="dest@example.org"
    )

    send_download_receipt_task(str(transfer.id), str(recipient.id))

    html = mail.outbox[0].alternatives[0][0]
    assert "{#" not in html and "#}" not in html
