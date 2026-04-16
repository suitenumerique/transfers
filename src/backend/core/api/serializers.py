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
    has_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "status",
            "sharing_mode",
            "sensitive",
            "has_password",
            "expires_at",
            "revoked_at",
            "created_at",
            "file_count",
            "total_size",
            "consulted",
            "downloaded",
        ]
        read_only_fields = fields


class TransferDetailSerializer(serializers.ModelSerializer):
    """Full serializer for transfer detail."""

    files = TransferFileSerializer(many=True, read_only=True)
    recipients = TransferRecipientSerializer(many=True, read_only=True)
    has_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "status",
            "sharing_mode",
            "sensitive",
            "has_password",
            "public_token",
            "upload_completed_at",
            "expires_at",
            "revoked_at",
            "files_deleted_at",
            "created_at",
            "files",
            "recipients",
        ]
        read_only_fields = fields


class _TransferFileCreateSerializer(serializers.Serializer):
    """Nested serializer: a single file to attach to a new transfer."""

    filename = serializers.CharField(max_length=255, required=True)
    size = serializers.IntegerField(min_value=1, required=True)
    mime_type = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )

    def validate_size(self, value):
        if value > settings.TRANSFER_MAX_FILE_SIZE:
            max_go = settings.TRANSFER_MAX_FILE_SIZE // (1024**3)
            raise serializers.ValidationError(
                f"File exceeds maximum size of {max_go} Go."
            )
        return value


class TransferCreateSerializer(serializers.Serializer):
    """Serializer to create a transfer + all its files in a single call.

    The client sends transfer-level metadata plus the list of files to attach.
    The viewset creates the Transfer, creates one TransferFile per entry, and
    initiates the S3 multipart upload for each — all in one DB transaction.
    The response mirrors the request: the transfer descriptor plus a parallel
    list of per-file upload descriptors the browser uses to push chunks.
    """

    title = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    expires_in_days = serializers.ChoiceField(
        choices=[(d, f"{d} jours") for d in settings.TRANSFER_EXPIRY_CHOICES],
        required=False,
        default=settings.TRANSFER_DEFAULT_EXPIRY_DAYS,
    )
    sensitive = serializers.BooleanField(required=False, default=False)
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        min_length=8,
        max_length=128,
        default="",
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
    files = _TransferFileCreateSerializer(many=True, required=True)

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

    def validate_files(self, value):
        if not value:
            raise serializers.ValidationError("At least one file is required.")
        if len(value) > settings.TRANSFER_MAX_FILES_PER_TRANSFER:
            raise serializers.ValidationError(
                f"A transfer cannot contain more than "
                f"{settings.TRANSFER_MAX_FILES_PER_TRANSFER} files."
            )
        total_size = sum(f["size"] for f in value)
        if total_size > settings.TRANSFER_MAX_TOTAL_SIZE:
            max_go = settings.TRANSFER_MAX_TOTAL_SIZE // (1024**3)
            raise serializers.ValidationError(
                f"Total transfer size exceeds maximum of {max_go} Go."
            )
        return value


class _PartETagSerializer(serializers.Serializer):
    """A single uploaded part, as reported by the browser."""

    PartNumber = serializers.IntegerField(min_value=1)
    ETag = serializers.CharField()


class TransferSignPartSerializer(serializers.Serializer):
    """Request a presigned URL to upload a specific part."""

    transfer_file_id = serializers.UUIDField()
    part_number = serializers.IntegerField(min_value=1, max_value=10000)


class TransferCompleteUploadSerializer(serializers.Serializer):
    """Complete a multipart upload after all parts have been uploaded."""

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
        ]
        read_only_fields = fields

    def get_files(self, obj):
        completed = obj.files.filter(upload_completed_at__isnull=False)
        return DownloadTransferFileSerializer(completed, many=True).data
