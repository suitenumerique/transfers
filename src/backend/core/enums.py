"""Core application enums."""

from django.db import models


class UserAbilities(models.TextChoices):
    """Defines the abilities a user can have."""

    CAN_CREATE_TRANSFER = "can_create_transfer", "Can create a transfer"


class TransferStatus(models.TextChoices):
    """Status of a transfer."""

    ACTIVE = "active", "Active"
    EXPIRED = "expired", "Expired"
    DEACTIVATED = "deactivated", "Deactivated"


class TransferEventType(models.TextChoices):
    """Types of events tracked on a transfer."""

    TRANSFER_CREATED = "transfer_created"
    EMAIL_SENT = "email_sent"
    LINK_OPENED = "link_opened"
    FILE_DOWNLOADED = "file_downloaded"
    TRANSFER_DEACTIVATED = "transfer_deactivated"
    TRANSFER_EXPIRED = "transfer_expired"
    FILES_DELETED = "files_deleted"


class SharingMode(models.TextChoices):
    """How the transfer link is shared."""

    EMAIL = "email", "Email"
    LINK = "link", "Link"


class ActorType(models.TextChoices):
    """Who performed the action."""

    AGENT = "agent", "Agent"
    EXTERNAL = "external", "External"
