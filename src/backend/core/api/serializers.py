"""Client serializers for the transfers core app."""

import re

from django.conf import settings

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import models
from core.enums import SharingMode
from core.services import encryption, safe_http
from core.services.recipient_activity import activity_by_recipient
from core.templatetags.humanize_size import humanize_size

# URL-safe base64 alphabet, no padding required. The frontend ships exactly
# 43 chars for a 256-bit key, but accept the padded 44-char form too so a
# client that fails to strip "=" still works. The field's ``max_length``
# bounds the overall length; this bounds the alphabet.
_ENCRYPTION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")

# Per-chunk overhead the browser's AES-GCM helper prepends (IV) and appends
# (GCM tag) to every encrypted chunk. The frontend's encryption module and
# the recipient Service Worker share this constant; the value must stay in
# sync across all three.
CRYPTO_OVERHEAD_PER_CHUNK = 12 + 16


def validate_encryption_key(value):
    """base64url key material only, decoding to a full AES-256 key, so a
    malformed value can't be stored and later served as an un-decryptable
    key."""
    if not value:
        return value
    if not _ENCRYPTION_KEY_RE.match(value):
        raise serializers.ValidationError(
            "Must be URL-safe base64 (A-Z, a-z, 0-9, '-', '_'; '=' padding optional)."
        )
    try:
        encryption.decode_key(value)
    except ValueError as err:
        raise serializers.ValidationError(
            "Must decode to a 32-byte AES-256 key."
        ) from err
    return value


def single_line(value: str) -> str:
    """Join the lines of a depositor's text: in a plain-text email, an
    embedded line break would let it pass as a line of the message."""
    return " ".join(value.splitlines())


def _expected_ciphertext_size(plaintext_size: int, chunk_size: int) -> int:
    """Total ciphertext bytes that will land in S3 for a given plaintext +
    chunk size, mirroring the browser's encryption layout. Used to verify
    the client-declared ``size`` matches what its plaintext + chunk params
    imply.
    """
    if plaintext_size <= 0:
        return CRYPTO_OVERHEAD_PER_CHUNK
    chunks = -(-plaintext_size // chunk_size)  # ceiling division
    return plaintext_size + chunks * CRYPTO_OVERHEAD_PER_CHUNK


class AbilitiesModelSerializer(serializers.ModelSerializer):
    """A ModelSerializer that dynamically adds an ``abilities`` field."""

    def __init__(self, *args, **kwargs):
        if not hasattr(self, "exclude_abilities"):
            self.exclude_abilities = kwargs.pop("exclude_abilities", False)
        super().__init__(*args, **kwargs)

        if not self.exclude_abilities:
            abilities_field = serializers.SerializerMethodField(read_only=True)
            self.fields["abilities"] = abilities_field

    @extend_schema_field(
        {
            "type": "object",
            "description": "Instance permissions and capabilities",
            "additionalProperties": {"type": "boolean"},
            "nullable": True,
        }
    )
    def get_abilities(self, instance):
        request = self.context.get("request")
        if not request:
            return {}
        if isinstance(instance, models.User):
            return instance.get_abilities()
        return instance.get_abilities(request.user)


class UserSerializer(AbilitiesModelSerializer):
    """Serialize users."""

    class Meta:
        model = models.User
        fields = ["id", "email", "full_name"]
        read_only_fields = fields

    @extend_schema_field(
        {
            "type": "object",
            "description": "User abilities",
            "additionalProperties": {"type": "boolean"},
        }
    )
    def get_abilities(self, instance):
        return super().get_abilities(instance)


class UserWithAbilitiesSerializer(UserSerializer):
    """Serialize users with abilities."""

    exclude_abilities = False


class UserWithoutAbilitiesSerializer(UserSerializer):
    """Serialize users without abilities."""

    exclude_abilities = True


# -- Transfer serializers --


class TransferRecipientSerializer(serializers.ModelSerializer):
    """A recipient with its delivery / activity state.

    ``status`` collapses what we can honestly observe into one word the UI
    maps to an icon: ``sending`` (invitation task still running), ``failed``
    (task done, this email never left), ``sent`` (relay accepted it — we
    never know about mailbox delivery, so there is no "received"),
    ``opened`` (they followed their personal link), ``downloaded`` (at least
    one file; ``downloaded_file_count`` says how many). The activity map is
    computed once per transfer by the parent serializer and handed down via
    context, so a 50-recipient detail costs one events query, not fifty.
    """

    status = serializers.SerializerMethodField()
    opened_at = serializers.SerializerMethodField()
    downloaded_at = serializers.SerializerMethodField()
    downloaded_file_count = serializers.SerializerMethodField()

    class Meta:
        model = models.TransferRecipient
        fields = [
            "id",
            "email",
            "email_sent_at",
            "status",
            "opened_at",
            "downloaded_at",
            "downloaded_file_count",
        ]
        read_only_fields = fields

    def _activity(self, obj):
        activity = self.context.get("recipient_activity")
        if activity is None:
            # Standalone use (no parent to precompute): fall back to a query
            # per transfer, cached on the context for sibling rows.
            activity = activity_by_recipient(obj.transfer_id)
            self.context["recipient_activity"] = activity
        return activity.get(obj.id)

    @extend_schema_field(
        {
            "type": "string",
            "enum": ["sending", "failed", "sent", "opened", "downloaded"],
        }
    )
    def get_status(self, obj) -> str:
        if obj.email_sent_at is None:
            transfer = self.context.get("recipient_transfer") or obj.transfer
            return (
                "sending" if transfer.notifications_completed_at is None else "failed"
            )
        activity = self._activity(obj)
        if activity is None:
            return "sent"
        if activity.downloaded_file_ids:
            return "downloaded"
        if activity.opened_at is not None:
            return "opened"
        return "sent"

    @extend_schema_field({"type": "string", "format": "date-time", "nullable": True})
    def get_opened_at(self, obj):
        activity = self._activity(obj)
        return activity.opened_at if activity else None

    @extend_schema_field({"type": "string", "format": "date-time", "nullable": True})
    def get_downloaded_at(self, obj):
        activity = self._activity(obj)
        return activity.downloaded_at if activity else None

    @extend_schema_field({"type": "integer"})
    def get_downloaded_file_count(self, obj) -> int:
        activity = self._activity(obj)
        return len(activity.downloaded_file_ids) if activity else 0


class TransferFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferFile
        fields = [
            "id",
            "filename",
            "size",
            "plaintext_size",
            "mime_type",
            "created_at",
            "scan_status",
            "scan_error_kind",
        ]
        read_only_fields = fields


class TransferEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferEvent
        fields = [
            "id",
            "transfer_id",
            "recipient_id",
            "event_type",
            "actor_type",
            "actor_id",
            "ip",
            "user_agent",
            "payload",
            "created_at",
        ]
        read_only_fields = fields


# Who an inbound transfer came from, and where it was deposited.
_DEPOSIT_FIELDS = (
    "direction",
    "deposit_space",
    "inbox_email",
    "depositor_name",
    "depositor_email",
)


class TransferRenameSerializer(serializers.ModelSerializer):
    """The one field an owner may change on a finalized transfer."""

    title = serializers.CharField(max_length=80)

    class Meta:
        model = models.Transfer
        fields = ["title"]


class TransferListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for transfer list.

    Reads annotated fields (``_file_count``, ``_total_size``, ``_consulted``,
    ``_downloaded``) populated by ``TransferViewSet.get_queryset()`` to avoid
    N+1 queries on the list endpoint.
    """

    file_count = serializers.IntegerField(source="_file_count", read_only=True)
    total_size = serializers.IntegerField(source="_total_size", read_only=True)
    consulted = serializers.BooleanField(source="_consulted", read_only=True)
    downloaded = serializers.BooleanField(source="_downloaded", read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "status",
            "sharing_mode",
            "expires_at",
            "deactivated_at",
            "created_at",
            "file_count",
            "total_size",
            "consulted",
            "downloaded",
            "auto_archive_on_download",
            "pending_deletion_at",
            "deactivation_reason",
            "confidential",
            *_DEPOSIT_FIELDS,
        ]
        read_only_fields = fields


class TransferDetailSerializer(serializers.ModelSerializer):
    """Full serializer for transfer detail."""

    files = TransferFileSerializer(many=True, read_only=True)
    recipients = TransferRecipientSerializer(many=True, read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "status",
            "sharing_mode",
            "public_token",
            "expires_at",
            "deactivated_at",
            "created_at",
            "notifications_completed_at",
            "files",
            "recipients",
            "auto_archive_on_download",
            "notify_on_download",
            "pending_deletion_at",
            "deactivation_reason",
            "confidential",
            "encryption_chunk_size",
            *_DEPOSIT_FIELDS,
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        # Precompute the per-recipient activity once for the nested
        # recipient rows (see TransferRecipientSerializer._activity).
        self.context["recipient_transfer"] = instance
        self.context["recipient_activity"] = activity_by_recipient(instance.id)
        return super().to_representation(instance)


class DraftAddFileSerializer(serializers.Serializer):
    """POST /drafts/add-file/ — attach a file to a draft, creating the draft
    on the fly if ``draft_id`` is omitted.

    Drafts hold files-in-transit; they carry no metadata of their own. A
    draft is born as a side-effect of the first ``add-file`` call, and
    every subsequent drop passes back ``draft_id`` to bind to the same
    draft. Transfer-level metadata (title, sharing_mode, recipients,
    expires_in_days) is set only at finalize time, and populates
    the freshly-created ``Transfer`` there — see ``TransferFinalizeSerializer``.

    Two attach modes coexist: browser-side multipart upload (no
    ``source_url``), and server-side Drive import (``source_url`` set to a
    public permalink). Drive bytes are fetched and encrypted at finalize,
    not here, because encryption needs the key and the key only reaches
    us at finalize (in non-confidential mode).

    Per-file size is checked here; cumulative limits (file count, total
    draft size) live in the viewset because they depend on what the target
    draft already holds.

    Every transfer is encrypted client-side, so ``size`` is always the
    ciphertext size that lands in S3 and ``plaintext_size`` (the file's
    pre-encryption size, needed by the recipient SW for ``Content-Length``)
    is always required. The chunk size used to encrypt is
    ``settings.TRANSFER_CHUNK_SIZE`` (also returned in ``/api/v1.0/config/``);
    the client never negotiates it, so it can't disagree with the recipient
    SW about decryption boundaries. ``size`` is cross-checked against
    ``plaintext_size`` + that chunk size so a malformed caller is rejected.
    """

    draft_id = serializers.UUIDField(required=False, allow_null=True)
    filename = serializers.CharField(max_length=255, required=True)
    # ``size`` is the ciphertext size that lands in S3 (plaintext + per-chunk
    # GCM overhead). The frontend computes the expansion before declaring;
    # the head_object check at complete-upload validates against it as-is.
    size = serializers.IntegerField(min_value=1, required=True)
    plaintext_size = serializers.IntegerField(min_value=1, required=True)
    mime_type = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    source_url = serializers.URLField(
        max_length=2048, required=False, allow_blank=True, default=""
    )

    def validate_source_url(self, value):
        # The worker fetches this URL server-side: only the configured Drive
        # instance is acceptable, and nothing at all when Drive is off.
        if value and not safe_http.is_drive_url(value):
            raise serializers.ValidationError(
                "Only files from the configured Drive can be imported."
            )
        return value

    def validate_size(self, value):
        # The viewset sets the cap: deposits use a lower one.
        max_file_size = self.context.get(
            "max_file_size", settings.TRANSFER_MAX_FILE_SIZE
        )
        if value > max_file_size:
            raise serializers.ValidationError(
                f"File exceeds maximum size of {humanize_size(max_file_size)}."
            )
        return value

    def validate(self, attrs):
        # Cross-check the declared ciphertext ``size`` against the canonical
        # chunk size the recipient SW will use to peel chunks. The chunk size
        # is server-side (settings.TRANSFER_CHUNK_SIZE, echoed on /config/)
        # so the client builds size from the same value; a mismatch here
        # means a buggy or malicious caller.
        expected_ciphertext = _expected_ciphertext_size(
            attrs["plaintext_size"], settings.TRANSFER_CHUNK_SIZE
        )
        if attrs["size"] != expected_ciphertext:
            raise serializers.ValidationError(
                {
                    "size": (
                        f"size ({attrs['size']}) does not match the "
                        f"expected ciphertext size ({expected_ciphertext}) "
                        f"for plaintext_size={attrs['plaintext_size']} at "
                        f"chunk size {settings.TRANSFER_CHUNK_SIZE}."
                    )
                }
            )
        return attrs


class DraftFileStateSerializer(serializers.ModelSerializer):
    """Lightweight projection of a draft's file rows for the polling
    endpoint — exposes just enough state for the frontend to render
    per-file progress for server-side Drive imports."""

    state = serializers.SerializerMethodField()
    scan_submitted = serializers.SerializerMethodField()

    class Meta:
        model = models.TransferFile
        fields = [
            "id",
            "filename",
            "size",
            "mime_type",
            "state",
            "source_url",
            "scan_status",
            "scan_error_kind",
            "scan_submitted",
        ]
        read_only_fields = fields

    def get_state(self, obj) -> str:
        if obj.upload_completed_at is not None:
            return "done"
        if obj.source_url:
            return "importing"
        return "uploading"

    def get_scan_submitted(self, obj) -> bool:
        """Whether a scan is actually in flight. PENDING alone is ambiguous: a
        file sits PENDING with no scan running until finalize supplies the key.
        """
        return obj.scan_submitted_at is not None


class DraftDetailSerializer(serializers.ModelSerializer):
    """GET /drafts/{id}/ — frontend polls this while any file is
    server-side-importing, to observe transitions to ``done``."""

    files = DraftFileStateSerializer(many=True, read_only=True)

    class Meta:
        model = models.TransferDraft
        fields = ["id", "created_at", "files"]
        read_only_fields = fields


class DraftRemoveFileSerializer(serializers.Serializer):
    """POST /drafts/{id}/remove-file/ body — identifies the single file to
    detach. Matches the ``transfer_file_id`` pattern used by ``sign-part``
    and ``complete-upload`` so every file-scoped action on a draft keeps
    the same shape."""

    transfer_file_id = serializers.UUIDField()


class DraftFinalizeSerializer(serializers.Serializer):
    """POST /drafts/{id}/finalize/ body.

    Carries all transfer-level metadata (title, expires, sharing mode,
    recipients) — a draft holds files only, never metadata. Finalize is
    the single write that creates the Transfer row with its real values
    and reparents the draft's files to it.
    """

    title = serializers.CharField(
        max_length=80, required=False, allow_blank=True, default=""
    )
    expires_in_days = serializers.ChoiceField(
        choices=[(d, f"{d} jours") for d in settings.TRANSFER_EXPIRY_CHOICES],
        required=False,
        default=settings.TRANSFER_DEFAULT_EXPIRY_DAYS,
    )
    sharing_mode = serializers.ChoiceField(
        choices=SharingMode.choices,
        required=False,
        default=SharingMode.LINK,
    )
    recipients = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
        default=list,
        max_length=50,
    )
    # Opt-in: when true, the finalized Transfer deactivates itself (S3
    # delete + status DEACTIVATED) once every file has been downloaded at
    # least once.
    auto_archive_on_download = serializers.BooleanField(required=False, default=False)
    # Opt-in: email the sender each time a recipient has downloaded every
    # file. Email mode only in practice — attribution needs the per-recipient
    # token that only the emailed link carries; accepted and stored either way.
    notify_on_download = serializers.BooleanField(required=False, default=False)
    # Confidential transfers keep the decryption key out of our infra: the
    # recipient supplies it from the URL fragment (link) or by pasting it
    # (email / bare link). Non-confidential transfers post ``encryption_key``
    # here so the backend can store it and serve it to recipients (and, for
    # Drive imports, encrypt the fetched bytes server-side at finalize).
    confidential = serializers.BooleanField(required=False, default=False)
    encryption_key = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=64
    )

    def validate_encryption_key(self, value):
        return validate_encryption_key(value)

    def validate(self, attrs):
        mode = attrs.get("sharing_mode", SharingMode.LINK)
        recipients = attrs.get("recipients", [])
        if mode == SharingMode.EMAIL and not recipients:
            raise serializers.ValidationError(
                {"recipients": "At least one recipient is required in email mode."}
            )
        if mode == SharingMode.LINK and recipients:
            raise serializers.ValidationError(
                {"recipients": "Recipients are not allowed in link mode."}
            )
        # The key travels to us only for non-confidential transfers. In
        # confidential mode it must never reach the backend, so reject a
        # posted key outright; in normal mode it's required so the backend
        # can serve it to recipients.
        confidential = attrs.get("confidential", False)
        if confidential and not settings.TRANSFER_CONFIDENTIAL_ENABLED:
            raise serializers.ValidationError(
                {
                    "confidential": "Confidential transfers are disabled on this instance."
                }
            )
        key = attrs.get("encryption_key", "")
        if confidential and key:
            raise serializers.ValidationError(
                {"encryption_key": "A confidential transfer must not send the key."}
            )
        if not confidential and not key:
            raise serializers.ValidationError(
                {"encryption_key": "Required for a non-confidential transfer."}
            )
        return attrs


class _PartETagSerializer(serializers.Serializer):
    """A single uploaded part, as reported by the browser."""

    PartNumber = serializers.IntegerField(min_value=1)
    ETag = serializers.CharField()


class DraftSignPartSerializer(serializers.Serializer):
    """POST /drafts/{id}/sign-part/ — request a presigned URL for one part."""

    transfer_file_id = serializers.UUIDField()
    part_number = serializers.IntegerField(min_value=1, max_value=10000)


class DraftCompleteUploadSerializer(serializers.Serializer):
    """POST /drafts/{id}/complete-upload/ — finalise the S3 multipart once
    every part has been uploaded."""

    transfer_file_id = serializers.UUIDField()
    parts = _PartETagSerializer(many=True)

    def validate_parts(self, value):
        if not value:
            raise serializers.ValidationError("At least one part is required.")
        return value


# -- Download serializers --


class DownloadTransferFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferFile
        fields = [
            "id",
            "filename",
            "size",
            "plaintext_size",
            "mime_type",
            "scan_status",
        ]
        read_only_fields = fields


class DownloadTransferSerializer(serializers.ModelSerializer):
    """Serializer for the public download page.

    Only files whose multipart upload has been completed are exposed.

    ``encryption_key`` is served here for non-confidential transfers so the
    recipient's Service Worker can decrypt transparently. This endpoint is
    ``AllowAny`` by design: the public token IS the capability, and a
    non-confidential transfer means "anyone with the link may read". For
    confidential transfers the column is empty (the key never reached us),
    so the recipient must supply it from the URL fragment or by pasting.
    """

    files = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = models.Transfer
        fields = [
            "title",
            "expires_at",
            "created_at",
            "files",
            "owner_name",
            "is_owner",
            "sharing_mode",
            "auto_archive_on_download",
            "notify_on_download",
            "confidential",
            "encryption_chunk_size",
            "encryption_key",
            # Only the owner reaches an inbound transfer here.
            "direction",
            "deposit_space",
            "depositor_name",
            "depositor_email",
        ]
        read_only_fields = fields

    @extend_schema_field({"type": "boolean"})
    def get_is_owner(self, obj) -> bool:
        # The download payload is served to anyone holding the link
        # (``AllowAny``), so we must not leak the owner's identity email.
        # The frontend only needs a boolean to tailor the auto-archive
        # copy ("…by another user." for the owner), so we resolve it
        # server-side from the authenticated session instead.
        request = self.context.get("request")
        return bool(
            request
            and request.user.is_authenticated
            and request.user.id == obj.owner_id
        )

    def get_files(self, obj):
        # Every TransferFile attached to a Transfer is complete by
        # construction (finalize refuses to run otherwise), but we keep the
        # filter as a belt-and-suspenders defense against any stray row.
        completed = obj.files.filter(upload_completed_at__isnull=False)
        return DownloadTransferFileSerializer(completed, many=True).data


# -- Deposit serializers --


class DepositSpaceSerializer(serializers.ModelSerializer):
    """An agent's deposit space. ``max_deposit_size`` is the effective cap;
    only the Django admin can change it."""

    deposit_count = serializers.IntegerField(read_only=True)
    max_deposit_size = serializers.IntegerField(
        source="effective_max_deposit_size", read_only=True
    )
    retention_days = serializers.IntegerField(
        required=False, default=settings.DEPOSIT_SPACE_DEFAULT_RETENTION_DAYS
    )

    class Meta:
        model = models.DepositSpace
        fields = [
            "id",
            "name",
            "link_token",
            "retention_days",
            "max_deposit_size",
            "revoked_at",
            "created_at",
            "deposit_count",
        ]
        read_only_fields = ["id", "link_token", "revoked_at", "created_at"]

    def validate_name(self, value):
        return single_line(value)

    def validate_retention_days(self, value):
        if value not in settings.DEPOSIT_SPACE_RETENTION_CHOICES:
            raise serializers.ValidationError(
                f"Must be one of {settings.DEPOSIT_SPACE_RETENTION_CHOICES}."
            )
        return value


class PublicDepositSpaceSerializer(serializers.ModelSerializer):
    """What a depositor sees of a space: never the owner's email."""

    owner_name = serializers.SerializerMethodField()
    max_deposit_size = serializers.IntegerField(
        source="effective_max_deposit_size", read_only=True
    )
    max_files = serializers.SerializerMethodField()

    class Meta:
        model = models.DepositSpace
        fields = ["name", "owner_name", "max_deposit_size", "max_files"]
        read_only_fields = fields

    def get_owner_name(self, obj) -> str:
        return obj.owner.full_name or ""

    def get_max_files(self, obj) -> int:
        return settings.TRANSFER_MAX_FILES_PER_TRANSFER


class DepositChallengeCreateSerializer(serializers.Serializer):
    """POST /deposit-challenges/: a deposit space's link token or, for an
    inbox send, an agent's email, and who the depositor is."""

    space_token = serializers.CharField(required=False, max_length=64)
    recipient_email = serializers.EmailField(required=False)
    depositor_name = serializers.CharField(max_length=100)
    depositor_email = serializers.EmailField()

    def validate_depositor_name(self, value):
        return single_line(value)

    def validate(self, attrs):
        if bool(attrs.get("space_token")) == bool(attrs.get("recipient_email")):
            raise serializers.ValidationError(
                "Give exactly one of space_token and recipient_email."
            )
        return attrs


class DepositVerifySerializer(serializers.Serializer):
    code = serializers.RegexField(r"^[0-9]{6}\Z")


class InboxClaimSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)


class DepositAddFileSerializer(DraftAddFileSerializer):
    """Deposits are browser uploads only: no server-side Drive import."""

    def validate_source_url(self, value):
        if value:
            raise serializers.ValidationError("Deposits cannot import from Drive.")
        return value

    def validate_filename(self, value):
        return single_line(value)


class DepositFinalizeSerializer(serializers.Serializer):
    """POST /deposit-drafts/{id}/finalize/. A deposit is never confidential:
    its owner decrypts with the stored key, and the scanner reads it."""

    title = serializers.CharField(
        max_length=80, required=False, allow_blank=True, default=""
    )
    encryption_key = serializers.CharField(max_length=64)

    def validate_title(self, value):
        return single_line(value)

    def validate_encryption_key(self, value):
        return validate_encryption_key(value)


class DepositReceiptSerializer(serializers.ModelSerializer):
    """What finalize answers the depositor. No token, no key: the depositor
    has no access to the files once sent."""

    file_count = serializers.SerializerMethodField()
    total_size = serializers.SerializerMethodField()

    class Meta:
        model = models.Transfer
        fields = ["title", "file_count", "total_size", "created_at"]
        read_only_fields = fields

    def get_file_count(self, obj) -> int:
        return len(obj.files.all())

    def get_total_size(self, obj) -> int:
        return sum(f.plaintext_size or f.size for f in obj.files.all())
