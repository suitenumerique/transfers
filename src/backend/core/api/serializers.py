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
