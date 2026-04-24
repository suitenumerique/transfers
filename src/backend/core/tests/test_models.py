"""Tests for Transfer models."""

from datetime import timedelta

from django.utils import timezone

import pytest

from core.enums import TransferStatus
from core.factories import TransferFactory


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
        transfer = TransferFactory(status=TransferStatus.DEACTIVATED)
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
