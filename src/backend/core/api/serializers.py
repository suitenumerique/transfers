"""Client serializers for the transferts core app."""

from django.conf import settings

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import models
from core.enums import SharingMode


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
    class Meta:
        model = models.TransferRecipient
        fields = ["id", "email", "email_sent_at"]
        read_only_fields = fields


class TransferFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferFile
        fields = ["id", "filename", "size", "mime_type", "created_at"]
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
            "pending_deletion_at",
            "deactivation_reason",
        ]
        read_only_fields = fields


class DraftAddFileSerializer(serializers.Serializer):
    """POST /drafts/add-file/ — attach a file to a draft, creating the draft
    on the fly if ``draft_id`` is omitted.

    Drafts hold files-in-transit; they carry no metadata of their own. A
    draft is born as a side-effect of the first ``add-file`` call, and
    every subsequent drop passes back ``draft_id`` to bind to the same
    draft. Transfer-level metadata (title, sharing_mode, recipients,
    expires_in_days, sensitive) is set only at finalize time, and populates
    the freshly-created ``Transfer`` there — see ``TransferFinalizeSerializer``.

    Two attach modes coexist: browser-side multipart upload (no
    ``source_url``), and server-side Drive import (``source_url`` set to a
    public permalink — the backend fetches the bytes via a celery task, no
    multipart ceremony exposed to the client).

    Per-file size is checked here; cumulative limits (file count, total
    draft size) live in the viewset because they depend on what the target
    draft already holds.
    """

    draft_id = serializers.UUIDField(required=False, allow_null=True)
    filename = serializers.CharField(max_length=255, required=True)
    size = serializers.IntegerField(min_value=1, required=True)
    mime_type = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    source_url = serializers.URLField(
        max_length=2048, required=False, allow_blank=True, default=""
    )

    def validate_size(self, value):
        if value > settings.TRANSFER_MAX_FILE_SIZE:
            max_go = settings.TRANSFER_MAX_FILE_SIZE // (1024**3)
            raise serializers.ValidationError(
                f"File exceeds maximum size of {max_go} Go."
            )
        return value


class DraftFileStateSerializer(serializers.ModelSerializer):
    """Lightweight projection of a draft's file rows for the polling
    endpoint — exposes just enough state for the frontend to render
    per-file progress for server-side Drive imports."""

    state = serializers.SerializerMethodField()

    class Meta:
        model = models.TransferFile
        fields = [
            "id",
            "filename",
            "size",
            "mime_type",
            "state",
            "source_url",
        ]
        read_only_fields = fields

    def get_state(self, obj) -> str:
        if obj.upload_completed_at is not None:
            return "done"
        if obj.source_url:
            return "importing"
        return "uploading"


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
        fields = ["id", "filename", "size", "mime_type"]
        read_only_fields = fields


class DownloadTransferSerializer(serializers.ModelSerializer):
    """Serializer for the public download page.

    Only files whose multipart upload has been completed are exposed.
    """

    files = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    owner_email = serializers.CharField(source="owner.email", read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "title",
            "expires_at",
            "created_at",
            "files",
            "owner_name",
            "owner_email",
            "sharing_mode",
            "auto_archive_on_download",
        ]
        read_only_fields = fields

    def get_files(self, obj):
        # Every TransferFile attached to a Transfer is complete by
        # construction (finalize refuses to run otherwise), but we keep the
        # filter as a belt-and-suspenders defense against any stray row.
        completed = obj.files.filter(upload_completed_at__isnull=False)
        return DownloadTransferFileSerializer(completed, many=True).data
