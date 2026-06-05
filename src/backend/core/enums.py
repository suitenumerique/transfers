"""Core application enums."""

from django.db import models


class UserAbilities(models.TextChoices):
    """Defines the abilities a user can have."""

    CAN_CREATE_TRANSFER = "can_create_transfer", "Can create a transfer"


class TransferStatus(models.TextChoices):
    """Status of a transfer.

    Only three states: ACTIVE (link live), PENDING_FILE_DELETION (link
    closed, S3 purge scheduled) and DEACTIVATED (terminal — link closed,
    bytes gone). The *why* of the deactivation is carried by
    ``DeactivationReason`` on the Transfer row, independent of the state
    machine.
    """

    ACTIVE = "active", "Active"
    PENDING_FILE_DELETION = "pending_file_deletion", "Pending file deletion"
    DEACTIVATED = "deactivated", "Deactivated"


class DeactivationReason(models.TextChoices):
    """Why a transfer was deactivated.

    Populated at the ACTIVE → PENDING_FILE_DELETION transition and carried
    through to DEACTIVATED. Null while the transfer is still ACTIVE.
    """

    MANUAL = "manual", "Manually deactivated"
    EXPIRED = "expired", "Expired"
    FIRST_DOWNLOAD = "first_download", "Deactivated after first full download"


class TransferEventType(models.TextChoices):
    """Types of events tracked on a transfer."""

    TRANSFER_CREATED = "transfer_created"
    EMAIL_SENT = "email_sent"
    LINK_OPENED = "link_opened"
    FILE_DOWNLOADED = "file_downloaded"
    # Deactivation events mirror the three DeactivationReason values.
    TRANSFER_DEACTIVATED_MANUALLY = "transfer_deactivated_manually"
    TRANSFER_DEACTIVATED_AFTER_FIRST_DOWNLOAD = (
        "transfer_deactivated_after_first_download"
    )
    TRANSFER_DEACTIVATED_AFTER_EXPIRY = "transfer_deactivated_after_expiry"
    FILE_DELETED = "file_deleted"


class ScanStatus(models.TextChoices):
    """Antivirus scan state of a file.

    A file is born ``PENDING`` and is only downloadable once it reaches
    ``CLEAN``. ``INFECTED`` and ``ERROR`` are terminal blocks — the download
    path fails closed on anything that isn't ``CLEAN`` or ``SKIPPED``.
    ``SKIPPED`` means scanning was disabled on this instance: the file was
    never scanned, so it carries no "clean" claim, but stays downloadable.
    Transitions are driven by the clamav file-scanner webhook, never the user.
    """

    PENDING = "pending", "Pending"
    CLEAN = "clean", "Clean"
    INFECTED = "infected", "Infected"
    ERROR = "error", "Error"
    SKIPPED = "skipped", "Skipped"


class SharingMode(models.TextChoices):
    """How the transfer link is shared."""

    EMAIL = "email", "Email"
    LINK = "link", "Link"


class ActorType(models.TextChoices):
    """Who performed the action."""

    AGENT = "agent", "Agent"
    EXTERNAL = "external", "External"
