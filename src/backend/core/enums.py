"""Core application enums."""

from django.db import models


class UserAbilities(models.TextChoices):
    """Defines the abilities a user can have."""

    CAN_CREATE_TRANSFER = "can_create_transfer", "Can create a transfer"
