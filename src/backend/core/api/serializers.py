"""Client serializers for the transferts core app."""


from django.conf import settings

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core import models


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


class TransferRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferRecipient
        fields = ["id", "email"]
        read_only_fields = ["id"]


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

    file_count = serializers.IntegerField(source="files.count", read_only=True)
    total_size = serializers.SerializerMethodField()
    recipient_count = serializers.IntegerField(
        source="recipients.count", read_only=True
    )

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "status",
            "has_password",
            "expires_at",
            "revoked_at",
            "created_at",
            "file_count",
            "total_size",
            "recipient_count",
        ]
        read_only_fields = fields

    def get_total_size(self, obj) -> int:
        return sum(f.size for f in obj.files.all())


class TransferDetailSerializer(serializers.ModelSerializer):
    """Full serializer for transfer detail."""

    files = TransferFileSerializer(many=True, read_only=True)
    recipients = TransferRecipientSerializer(many=True, read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "id",
            "title",
            "message",
            "status",
            "has_password",
            "public_token",
            "expires_at",
            "revoked_at",
            "created_at",
            "files",
            "recipients",
        ]
        read_only_fields = fields


class TransferCreateSerializer(serializers.Serializer):
    """Serializer for creating a transfer (handles files via multipart)."""

    title = serializers.CharField(max_length=255, required=False, default="")
    message = serializers.CharField(required=False, default="")
    password = serializers.CharField(required=False, default="", write_only=True)
    expires_in_days = serializers.IntegerField(required=False)
    recipients = serializers.ListField(
        child=serializers.EmailField(),
        min_length=1,
    )

    def validate_expires_in_days(self, value):
        max_days = settings.TRANSFER_MAX_EXPIRY_DAYS
        if value < 1 or value > max_days:
            raise serializers.ValidationError(
                f"Must be between 1 and {max_days} days."
            )
        return value

    def get_expires_in_days(self, validated_data):
        return validated_data.get(
            "expires_in_days", settings.TRANSFER_DEFAULT_EXPIRY_DAYS
        )


# -- Download serializers --


class DownloadTransferFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferFile
        fields = ["id", "filename", "size", "mime_type"]
        read_only_fields = fields


class DownloadTransferLockedSerializer(serializers.ModelSerializer):
    """Minimal serializer when transfer is password-protected (before unlock)."""

    has_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "title",
            "has_password",
        ]
        read_only_fields = fields


class DownloadTransferSerializer(serializers.ModelSerializer):
    """Full serializer for the download page (no password or already unlocked)."""

    files = DownloadTransferFileSerializer(many=True, read_only=True)
    has_password = serializers.BooleanField(read_only=True)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    owner_email = serializers.CharField(source="owner.email", read_only=True)

    class Meta:
        model = models.Transfer
        fields = [
            "title",
            "message",
            "has_password",
            "expires_at",
            "created_at",
            "files",
            "owner_name",
            "owner_email",
        ]
        read_only_fields = fields


class VerifyPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(required=True)
