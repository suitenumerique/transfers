"""Core application factories."""

from django.conf import settings
from django.contrib.auth.hashers import make_password

import factory.fuzzy

from core import models


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
