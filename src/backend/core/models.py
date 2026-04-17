"""Models for the transferts core application."""

import secrets
import uuid

from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.core import validators
from django.db import models
from django.utils import timezone

from timezone_field import TimeZoneField

from core.enums import (
    ActorType,
    SharingMode,
    TransferEventType,
    TransferStatus,
    UserAbilities,
)


class DuplicateEmailError(Exception):
    """Raised when an email is already associated with a pre-existing user."""

    def __init__(self, message=None, email=None):
        self.message = message
        self.email = email
        super().__init__(self.message)


class BaseModel(models.Model):
    """Abstract base model with UUID primary key and timestamps."""

    id = models.UUIDField(
        verbose_name="id",
        help_text="primary key for the record as UUID",
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(
        verbose_name="created on",
        help_text="date and time at which a record was created",
        auto_now_add=True,
        editable=False,
    )
    updated_at = models.DateTimeField(
        verbose_name="updated on",
        help_text="date and time at which a record was last updated",
        auto_now=True,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Call ``full_clean`` before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class UserManager(auth_models.UserManager):
    """Custom manager for User model."""

    def get_user_by_sub_or_email(self, sub, email):
        """Fetch existing user by sub or email."""
        try:
            return self.get(sub=sub)
        except self.model.DoesNotExist as err:
            if not email:
                return None

            if settings.OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION:
                try:
                    return self.get(email=email)
                except self.model.DoesNotExist:
                    pass
            elif (
                self.filter(email=email).exists()
                and not settings.OIDC_ALLOW_DUPLICATE_EMAILS
            ):
                raise DuplicateEmailError(
                    "We couldn't find a user with this sub but the email is already "
                    "associated with a registered user."
                ) from err
        return None


class User(AbstractBaseUser, BaseModel, auth_models.PermissionsMixin):
    """User model to work with OIDC only authentication."""

    sub_validator = validators.RegexValidator(
        regex=r"^[\w.@+-:]+\Z",
        message=(
            "Enter a valid sub. This value may contain only letters, "
            "numbers, and @/./+/-/_/: characters."
        ),
    )

    sub = models.CharField(
        "sub",
        help_text=(
            "Required. 255 characters or fewer. "
            "Letters, numbers, and @/./+/-/_/: characters only."
        ),
        max_length=255,
        unique=True,
        validators=[sub_validator],
        blank=True,
        null=True,
    )

    full_name = models.CharField("full name", max_length=255, null=True, blank=True)
    email = models.EmailField("identity email address", blank=True, null=True)
    admin_email = models.EmailField(
        "admin email address", unique=True, blank=True, null=True
    )

    language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
        verbose_name="language",
        help_text="The language in which the user wants to see the interface.",
    )
    timezone = TimeZoneField(
        choices_display="WITH_GMT_OFFSET",
        use_pytz=False,
        default=settings.TIME_ZONE,
        help_text="The timezone in which the user wants to see times.",
    )
    is_staff = models.BooleanField(
        "staff status",
        default=False,
        help_text="Whether the user can log into this admin site.",
    )
    is_active = models.BooleanField(
        "active",
        default=True,
        help_text=(
            "Whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )

    objects = UserManager()

    USERNAME_FIELD = "admin_email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "core_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email or self.admin_email or str(self.id)

    def get_abilities(self):
        """Return abilities of the logged-in user."""
        return {
            UserAbilities.CAN_CREATE_TRANSFER: self.is_active,
        }


def _generate_public_token() -> str:
    return secrets.token_urlsafe(32)


class Transfer(BaseModel):
    """A file transfer created by an agent."""

    owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="transfers",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=TransferStatus.choices,
        default=TransferStatus.ACTIVE,
    )
    public_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        null=True,
        blank=True,
        default=None,
        help_text="Set once the transfer is finalized (all files uploaded). "
        "Until then, the transfer has no public link.",
    )
    upload_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once all TransferFile uploads have been completed and "
        "the transfer has been finalized. Until then, the transfer is not "
        "listed, not downloadable, and has no public token.",
    )
    sharing_mode = models.CharField(
        max_length=5,
        choices=SharingMode.choices,
        default=SharingMode.LINK,
    )
    sensitive = models.BooleanField(
        default=False,
        help_text=(
            "Reserved — the agent can flag a transfer as sensitive, but this "
            "flag has no runtime effect yet. Surfaced on the transfer detail "
            "for future product use."
        ),
    )

    class Meta:
        db_table = "core_transfer"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Transfer {self.id}"

    @property
    def is_expired(self) -> bool:
        return (
            self.status == TransferStatus.EXPIRED or self.expires_at <= timezone.now()
        )

    @property
    def is_revoked(self) -> bool:
        return self.status == TransferStatus.REVOKED

    @property
    def is_finalized(self) -> bool:
        return self.upload_completed_at is not None

    @property
    def is_accessible(self) -> bool:
        return (
            self.is_finalized
            and self.status == TransferStatus.ACTIVE
            and not self.is_expired
        )

    def abort_pending_uploads(self) -> None:
        """Abort every in-progress S3 multipart upload attached to this transfer.

        Best-effort: failures on an individual file are logged by the S3
        wrapper and swallowed so one broken file does not block the others.
        Files already completed — or that never started a multipart upload —
        are skipped.
        """
        from core.services import s3

        for tf in self.files.all():
            if tf.upload_id:
                s3.abort_multipart_upload(tf.s3_key, tf.upload_id)

    def delete_s3_objects(self) -> None:
        """Delete every S3 object attached to this transfer.

        Best-effort: failures on an individual file are logged by the S3
        wrapper and swallowed. Used when tearing down a transfer whose
        bytes are no longer needed (revoke, expiry cleanup).
        """
        from core.services import s3

        for tf in self.files.all():
            if tf.s3_key:
                s3.delete_object(tf.s3_key)


class TransferRecipient(BaseModel):
    """A recipient of a transfer (email mode only)."""

    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    email = models.EmailField()
    email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_transfer_recipient"
        unique_together = [("transfer", "email")]

    def __str__(self):
        return self.email


class TransferFile(BaseModel):
    """A file attached to a transfer."""

    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name="files",
    )
    filename = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    mime_type = models.CharField(max_length=255, blank=True, default="")
    s3_key = models.CharField(max_length=512)

    upload_id = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="S3 multipart upload id while the upload is in progress.",
    )
    upload_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once all parts have been uploaded and the multipart "
        "upload has been completed on S3.",
    )

    class Meta:
        db_table = "core_transfer_file"

    def __str__(self):
        return self.filename

    @property
    def is_upload_complete(self) -> bool:
        return self.upload_completed_at is not None


class TransferEvent(BaseModel):
    """An auditable event on a transfer. Not FK-constrained to survive deletion."""

    transfer_id = models.UUIDField(db_index=True)
    recipient_id = models.UUIDField(null=True, blank=True, db_index=True)
    event_type = models.CharField(
        max_length=30,
        choices=TransferEventType.choices,
    )
    actor_type = models.CharField(
        max_length=10,
        choices=ActorType.choices,
    )
    actor_id = models.UUIDField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "core_transfer_event"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} on {self.transfer_id}"
