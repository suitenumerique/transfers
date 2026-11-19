"""Core application factories."""

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone

import factory.fuzzy

from core import models
from core.enums import TransferDirection, TransferStatus


class UserFactory(factory.django.DjangoModelFactory):
    """A factory to create random users for testing purposes."""

    class Meta:
        model = models.User
        skip_postgeneration_save = True

    sub = factory.Sequence(lambda n: f"user{n!s}")
    email = factory.Faker("email")
    full_name = factory.Faker("name")
    language = factory.fuzzy.FuzzyChoice([lang[0] for lang in settings.LANGUAGES])
    password = make_password("password")


class TransferFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Transfer

    owner = factory.SubFactory(UserFactory)
    title = factory.Faker("sentence", nb_words=4)
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))
    status = TransferStatus.ACTIVE
    # A Transfer row only exists post-finalize, so every instance carries
    # a public token by default. Override in tests that need a custom one.
    public_token = factory.LazyFunction(lambda: secrets.token_urlsafe(32))


class DepositSpaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.DepositSpace

    owner = factory.SubFactory(UserFactory)
    name = factory.Faker("sentence", nb_words=3)
    retention_days = factory.LazyFunction(
        lambda: settings.DEPOSIT_SPACE_DEFAULT_RETENTION_DAYS
    )


class InboundTransferFactory(TransferFactory):
    """A deposit on a space, as finalize creates it."""

    direction = TransferDirection.INBOUND
    deposit_space = factory.SubFactory(
        DepositSpaceFactory, owner=factory.SelfAttribute("..owner")
    )
    depositor_name = factory.Faker("name")
    depositor_email = factory.Faker("email")
    encryption_chunk_size = factory.LazyFunction(lambda: settings.TRANSFER_CHUNK_SIZE)
    encryption_key = "A" * 43


class TransferDraftFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.TransferDraft

    owner = factory.SubFactory(UserFactory)


class TransferFileFactory(factory.django.DjangoModelFactory):
    """Factory for TransferFile.

    Produces a file attached to a finalized Transfer by default. Pass
    ``draft=draft, transfer=None`` to produce a draft-owned file — the
    model's check constraint enforces exactly one parent, so callers must
    pick one or the other.
    """

    class Meta:
        model = models.TransferFile

    transfer = factory.SubFactory(TransferFactory)
    draft = None
    filename = factory.Faker("file_name")
    size = factory.fuzzy.FuzzyInteger(1024, 10 * 1024 * 1024)
    mime_type = "application/octet-stream"
    s3_key = factory.LazyFunction(lambda: f"transfers/{uuid.uuid4()}/test-file.bin")
