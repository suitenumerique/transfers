"""API ViewSet for sharing public settings."""

from django.conf import settings

import rest_framework as drf
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny


class ConfigView(drf.views.APIView):
    """API ViewSet for sharing public settings."""

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["config"],
        responses={
            200: OpenApiResponse(
                description="A dictionary of public configuration settings.",
            )
        },
        description="Return a dictionary of public settings for the frontend.",
    )
    def get(self, request):
        """GET /api/v1.0/config/ — Return public settings."""
        return drf.response.Response(
            {
                "ENVIRONMENT": getattr(settings, "ENVIRONMENT", ""),
                "LANGUAGES": getattr(settings, "LANGUAGES", []),
                "LANGUAGE_CODE": getattr(settings, "LANGUAGE_CODE", "fr"),
                "TRANSFER_MAX_FILE_SIZE": settings.TRANSFER_MAX_FILE_SIZE,
                "TRANSFER_MAX_TOTAL_SIZE": settings.TRANSFER_MAX_TOTAL_SIZE,
                "TRANSFER_MAX_FILES_PER_TRANSFER": settings.TRANSFER_MAX_FILES_PER_TRANSFER,
                "TRANSFER_EXPIRY_CHOICES": settings.TRANSFER_EXPIRY_CHOICES,
                "TRANSFER_DEFAULT_EXPIRY_DAYS": settings.TRANSFER_DEFAULT_EXPIRY_DAYS,
            }
        )
