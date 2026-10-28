"""Database invariants of deposits."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

import pytest

from core.enums import TransferDirection
from core.factories import DepositSpaceFactory, InboundTransferFactory, UserFactory
from core.models import DepositChallenge, TransferDraft

pytestmark = pytest.mark.django_db


def _challenge(**fields):
    return DepositChallenge(
        depositor_email="dep@example.org",
        depositor_name="Camille",
        code_hash="x",
        expires_at=timezone.now() + timedelta(minutes=10),
        **fields,
    )


def test_challenge_has_exactly_one_target():
    space = DepositSpaceFactory()
    with pytest.raises(ValidationError):
        _challenge().save()
    with pytest.raises(ValidationError):
        _challenge(deposit_space=space, inbox_email="a@example.local").save()
    _challenge(deposit_space=space).save()
    _challenge(inbox_email="a@example.local").save()


def test_draft_belongs_to_a_user_or_a_challenge():
    challenge = _challenge(deposit_space=DepositSpaceFactory())
    challenge.save()
    with pytest.raises(ValidationError):
        TransferDraft(encryption_chunk_size=1).save()
    with pytest.raises(ValidationError):
        TransferDraft(owner=UserFactory(), deposit_challenge=challenge).save()
    TransferDraft(deposit_challenge=challenge, encryption_chunk_size=1).save()
    # One upload per challenge, down to the database.
    with pytest.raises(ValidationError):
        TransferDraft(deposit_challenge=challenge, encryption_chunk_size=1).save()
    with pytest.raises(IntegrityError), transaction.atomic():
        TransferDraft.objects.bulk_create(
            [TransferDraft(deposit_challenge=challenge, encryption_chunk_size=1)]
        )


def test_inbound_transfer_keeps_its_key():
    with pytest.raises(ValidationError):
        InboundTransferFactory(encryption_key="")
    with pytest.raises(ValidationError):
        InboundTransferFactory(confidential=True)


def test_space_cap_and_openness(settings):
    space = DepositSpaceFactory()
    assert space.effective_max_deposit_size == settings.DEPOSIT_MAX_TOTAL_SIZE
    space.max_deposit_size = 10
    assert space.effective_max_deposit_size == 10
    assert space.is_open
    space.expires_at = timezone.now() - timedelta(seconds=1)
    assert not space.is_open
    space.expires_at = timezone.now() + timedelta(days=1)
    assert space.is_open
    space.used_at = timezone.now()
    assert not space.is_open
    space.used_at = None
    space.owner.is_active = False
    assert not space.is_open
    assert InboundTransferFactory().direction == TransferDirection.INBOUND
    # An end-to-end deposit: its owner holds the key.
    InboundTransferFactory(confidential=True, encryption_key="")


def test_end_to_end_space_has_a_key_check():
    with pytest.raises(ValidationError):
        DepositSpaceFactory(confidential=True)
    with pytest.raises(ValidationError):
        DepositSpaceFactory(key_check="a" * 64)
    DepositSpaceFactory(confidential=True, key_check="a" * 64)
