"""Models for the transferts core application."""

import logging
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.core import validators
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils import timezone

from timezone_field import TimeZoneField

from core.enums import (
    ActorType,
    DeactivationReason,
    SharingMode,
    TransferEventType,
    TransferStatus,
    UserAbilities,
)

logger = logging.getLogger(__name__)


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
                    # Match case-insensitively: an OIDC provider may echo the
                    # same address with different casing across logins, and a
                    # case-sensitive lookup would mint a duplicate account.
                    return self.get(email__iexact=email)
                except self.model.DoesNotExist:
                    pass
                except self.model.MultipleObjectsReturned:
                    # Pre-existing duplicates differing only by case — pick a
                    # stable one rather than 500, but surface it: it's a
                    # data-quality issue an admin should reconcile. We log the
                    # user ids (not the email) to keep PII out of the logs.
                    duplicates = list(
                        self.filter(email__iexact=email).order_by("created_at")
                    )
                    logger.warning(
                        "Duplicate accounts share one email (case-insensitive); "
                        "selected the oldest. Reconcile these user ids: %s",
                        ", ".join(str(user.pk) for user in duplicates),
                    )
                    return duplicates[0]
            elif (
                self.filter(email__iexact=email).exists()
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
        regex=r"^[\w.@+\-:]+\Z",
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
    title = models.CharField(max_length=80, blank=True, default="")
    expires_at = models.DateTimeField()
    deactivated_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=TransferStatus.choices,
        default=TransferStatus.ACTIVE,
    )
    # Why the transfer was deactivated. Populated at the ACTIVE →
    # PENDING_FILE_DELETION transition (one of manual / expired /
    # first_download) and carried through to DEACTIVATED. Null while ACTIVE.
    deactivation_reason = models.CharField(
        max_length=16,
        choices=DeactivationReason.choices,
        null=True,
        blank=True,
    )
    public_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=_generate_public_token,
        help_text="Opaque token used in public download URLs. Populated at "
        "finalize time (= when the Transfer row is created).",
    )
    sharing_mode = models.CharField(
        max_length=5,
        choices=SharingMode.choices,
        default=SharingMode.LINK,
    )
    # Opt-in one-shot link: when true, the link is deactivated (status
    # flipped to PENDING_FILE_DELETION) the moment every file has been
    # downloaded at least once, and S3 objects are purged later by
    # ``delete_pending_transfer_files_task``. Defaults to false so the
    # behaviour stays opt-in.
    auto_archive_on_download = models.BooleanField(default=False)
    # Deadline after which the periodic sweep may delete this transfer's S3
    # objects. Populated at the ACTIVE → PENDING_FILE_DELETION transition,
    # null otherwise. The gap between the transition and this deadline lets
    # recipients' in-flight downloads finish before the bytes disappear.
    pending_deletion_at = models.DateTimeField(null=True, blank=True)
    notifications_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when ``send_recipient_invitations_task`` has run "
        "through every recipient (whether their delivery succeeded or not). "
        "The frontend polls this to know when to leave the 'sending…' state.",
    )

    class Meta:
        db_table = "core_transfer"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Transfer {self.id}"

    @property
    def is_expired(self) -> bool:
        """True iff the transfer's deadline has passed.

        Timing-only check — independent of status. A transfer whose sweep
        hasn't fired yet is still ``ACTIVE`` with a past ``expires_at``,
        and should be treated as expired by public-access gates.
        """
        return self.expires_at <= timezone.now()

    @property
    def is_deactivated(self) -> bool:
        return self.status in (TransferStatus.DEACTIVATED, TransferStatus.PENDING_FILE_DELETION)

    @property
    def is_accessible(self) -> bool:
        # A Transfer row exists iff it was finalized — drafts live in
        # ``TransferDraft`` and never promote to Transfer until finalize.
        # So accessibility only depends on status + expiry.
        return self.status == TransferStatus.ACTIVE and not self.is_expired

    def deactivate(self, reason: DeactivationReason) -> bool:
        """Transition ``ACTIVE → PENDING_FILE_DELETION`` with the given reason.

        Single entry point for the three deactivation flows (manual,
        expiry sweep, first-full-download auto-archive). Sets
        ``pending_deletion_at`` to ``now + TRANSFER_PURGE_DELAY_HOURS`` —
        the periodic sweep then wipes S3 and flips to DEACTIVATED once
        that deadline has passed. Audit events
        (``TRANSFER_DEACTIVATED_*``) are the caller's responsibility:
        they depend on *who* triggered the deactivation, which the model
        doesn't know.

        Returns True iff the transition was applied. A False return means
        another caller already moved the row out of ACTIVE — the caller
        should skip any follow-up audit event.
        """
        now = timezone.now()
        updated = Transfer.objects.filter(
            pk=self.pk,
            status=TransferStatus.ACTIVE,
        ).update(
            status=TransferStatus.PENDING_FILE_DELETION,
            deactivation_reason=reason,
            pending_deletion_at=now + timedelta(hours=settings.TRANSFER_PURGE_DELAY_HOURS),
            updated_at=now,
        )
        if updated:
            self.status = TransferStatus.PENDING_FILE_DELETION
            self.deactivation_reason = reason
            self.pending_deletion_at = now + timedelta(
                hours=settings.TRANSFER_PURGE_DELAY_HOURS
            )
        return bool(updated)

    def delete_s3_objects(self) -> bool:
        """Delete every S3 object attached to this transfer.

        Best-effort: failures on an individual file are logged by the S3
        wrapper and swallowed. Used when tearing down a transfer whose
        bytes are no longer needed (deactivation cleanup).

        Returns ``True`` iff every object was deleted without error, so the
        purge task can keep a transfer PENDING_FILE_DELETION for retry when
        S3 hiccups instead of declaring the bytes gone.
        """
        from core.services import s3

        return s3.best_effort_delete_objects_from_files(self.files.all())


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


class TransferDraft(BaseModel):
    """Ephemeral container for files being uploaded, before a Transfer exists.

    A draft is born on the first ``add-file`` call, accumulates files, and
    dies either at ``abort`` or at ``finalize`` — in the latter case a fresh
    ``Transfer`` is created and the draft's ``TransferFile`` rows are
    reparented to it (see ``TransferDraftViewSet.finalize``). Drafts are
    never surfaced publicly and hold no transfer-level metadata: title,
    sharing_mode, recipients and expiry all come from the finalize
    request body.
    """

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="drafts",
    )

    class Meta:
        db_table = "core_transfer_draft"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Draft {self.id}"


class TransferFile(BaseModel):
    """A file attached to a transfer or, during upload, to a draft.

    Exactly one of ``transfer`` / ``draft`` is set at any point in time —
    enforced by ``transferfile_exactly_one_parent`` at the DB level. At
    finalize the rows get reparented from the draft to the newly-created
    transfer in a single ``UPDATE``.
    """

    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name="files",
        null=True,
        blank=True,
    )
    draft = models.ForeignKey(
        TransferDraft,
        on_delete=models.CASCADE,
        related_name="files",
        null=True,
        blank=True,
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
    source_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
        help_text="Public Drive permalink when the file was imported "
        "server-side rather than uploaded by the browser. Preserved after "
        "import completes for audit — the bytes live in our S3 like any "
        "other file once ``upload_completed_at`` is set.",
    )

    class Meta:
        db_table = "core_transfer_file"
        constraints = [
            CheckConstraint(
                # Exactly one of transfer / draft must be set. This keeps the
                # file-to-parent relation single-valued regardless of which
                # entity owns the row at a given moment.
                check=(
                    Q(transfer__isnull=False, draft__isnull=True)
                    | Q(transfer__isnull=True, draft__isnull=False)
                ),
                name="transferfile_exactly_one_parent",
            ),
        ]

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
        max_length=64,
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
