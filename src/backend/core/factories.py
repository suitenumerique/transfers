"""Core application factories."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone

import factory.fuzzy

from core import models
from core.enums import TransferStatus


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


class TransferFileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.TransferFile

    transfer = factory.SubFactory(TransferFactory)
    filename = factory.Faker("file_name")
    size = factory.fuzzy.FuzzyInteger(1024, 10 * 1024 * 1024)
    mime_type = "application/octet-stream"
    s3_key = factory.LazyFunction(lambda: f"transfers/{uuid.uuid4()}/test-file.bin")


