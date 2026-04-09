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

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

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
        default=_generate_public_token,
    )
    sensitive = models.BooleanField(
        default=False,
        help_text="Marked as sensitive document by the agent. Behaviour TBD.",
    )

    class Meta:
        db_table = "core_transfer"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Transfer {self.public_token[:8]}"

    @property
    def is_expired(self) -> bool:
        return self.status == TransferStatus.EXPIRED or self.expires_at <= timezone.now()

    @property
    def is_revoked(self) -> bool:
        return self.status == TransferStatus.REVOKED

    @property
    def is_accessible(self) -> bool:
        return self.status == TransferStatus.ACTIVE and not self.is_expired


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

    class Meta:
        db_table = "core_transfer_file"

    def __str__(self):
        return self.filename


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
