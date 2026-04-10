"""Client serializers for the transferts core app."""


from django.conf import settings

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import models
from core.enums import TransferEventType


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
    """Lightweight serializer for transfer list."""

    filename = serializers.SerializerMethodField()
    filesize = serializers.SerializerMethodField()
    consulted = serializers.SerializerMethodField()
    downloaded = serializers.SerializerMethodField()

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "status",
            "sensitive",
            "expires_at",
            "revoked_at",
            "created_at",
            "filename",
            "filesize",
            "consulted",
            "downloaded",
        ]
        read_only_fields = fields

    def get_filename(self, obj) -> str:
        first = obj.files.first()
        return first.filename if first else ""

    def get_filesize(self, obj) -> int:
        first = obj.files.first()
        return first.size if first else 0

    def get_consulted(self, obj) -> bool:
        return models.TransferEvent.objects.filter(
            transfer_id=obj.id,
            event_type=TransferEventType.LINK_OPENED,
        ).exists()

    def get_downloaded(self, obj) -> bool:
        return models.TransferEvent.objects.filter(
            transfer_id=obj.id,
            event_type=TransferEventType.FILE_DOWNLOADED,
        ).exists()


class TransferDetailSerializer(serializers.ModelSerializer):
    """Full serializer for transfer detail."""

    files = TransferFileSerializer(many=True, read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "status",
            "sensitive",
            "public_token",
            "expires_at",
            "revoked_at",
            "files_deleted_at",
            "created_at",
            "files",
        ]
        read_only_fields = fields


class TransferCreateSerializer(serializers.Serializer):
    """Serializer for creating a transfer (handles files via multipart)."""

    title = serializers.CharField(max_length=255, required=False, default="")
    expires_in_days = serializers.ChoiceField(
        choices=[(d, f"{d} jours") for d in settings.TRANSFER_EXPIRY_CHOICES],
        required=False,
    )
    sensitive = serializers.BooleanField(required=False, default=False)

    def get_expires_in_days(self, validated_data):
        value = validated_data.get("expires_in_days")
        if value is not None:
            return int(value)
        return settings.TRANSFER_DEFAULT_EXPIRY_DAYS


# -- Download serializers --


class DownloadTransferFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferFile
        fields = ["id", "filename", "size", "mime_type"]
        read_only_fields = fields


class DownloadTransferSerializer(serializers.ModelSerializer):
    """Serializer for the public download page."""

    files = DownloadTransferFileSerializer(many=True, read_only=True)
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
