"""Tests for Transfer models."""

from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

import pytest

from core.enums import TransferStatus
from core.factories import TransferFactory, UserFactory
from core.models import User


@pytest.mark.django_db
class TestTransferModel:
    def test_public_token_generated(self):
        transfer = TransferFactory()
        assert transfer.public_token
        assert len(transfer.public_token) >= 32

    def test_public_token_unique(self):
        t1 = TransferFactory()
        t2 = TransferFactory()
        assert t1.public_token != t2.public_token

    def test_is_expired(self):
        # Timing-only check: the property depends on expires_at, not on
        # whatever status the sweep happens to have set yet.
        expired = TransferFactory(expires_at=timezone.now() - timedelta(hours=1))
        assert expired.is_expired

        active = TransferFactory(expires_at=timezone.now() + timedelta(days=1))
        assert not active.is_expired

    def test_is_deactivated(self):
        for status in (TransferStatus.DEACTIVATED, TransferStatus.PENDING_FILE_DELETION):
            transfer = TransferFactory(status=status)
            assert transfer.is_deactivated
            assert not transfer.is_accessible

    def test_is_accessible(self):
        active = TransferFactory(
            status=TransferStatus.ACTIVE,
            expires_at=timezone.now() + timedelta(days=1),
        )
        assert active.is_accessible

        expired = TransferFactory(
            status=TransferStatus.ACTIVE,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        assert not expired.is_accessible

        deactivated = TransferFactory(status=TransferStatus.DEACTIVATED)
        assert not deactivated.is_accessible


@pytest.mark.django_db
class TestUserManagerDuplicateEmail:
    def test_returns_oldest_and_logs_ids_not_email(self, settings):
        settings.OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION = True
        # Two accounts whose emails differ only by case (email isn't unique).
        older = UserFactory(sub="sub-older", email="dup@example.fr")
        newer = UserFactory(sub="sub-newer", email="DUP@example.fr")

        with patch("core.models.logger") as mock_logger:
            user = User.objects.get_user_by_sub_or_email(
                sub="unknown-sub", email="dup@example.fr"
            )

        # Falls back to the oldest of the duplicates rather than raising.
        assert user == older

        # The warning surfaces the user ids for reconciliation, but never the
        # email — PII must stay out of the logs.
        mock_logger.warning.assert_called_once()
        args = mock_logger.warning.call_args.args
        rendered = args[0] % args[1:]
        assert str(older.pk) in rendered
        assert str(newer.pk) in rendered
        assert "dup@example.fr" not in rendered
        assert "DUP@example.fr" not in rendered
