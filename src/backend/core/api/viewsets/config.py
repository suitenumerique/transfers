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
        payload = {
            "ENVIRONMENT": getattr(settings, "ENVIRONMENT", ""),
            "LANGUAGES": getattr(settings, "LANGUAGES", []),
            "LANGUAGE_CODE": getattr(settings, "LANGUAGE_CODE", "fr"),
            "TRANSFER_MAX_FILE_SIZE": settings.TRANSFER_MAX_FILE_SIZE,
            "TRANSFER_MAX_TOTAL_SIZE": settings.TRANSFER_MAX_TOTAL_SIZE,
            "TRANSFER_MAX_FILES_PER_TRANSFER": settings.TRANSFER_MAX_FILES_PER_TRANSFER,
            # Multipart part / crypto chunk size in bytes. Surfaced so the
            # frontend can declare a self-consistent encryption ``size`` upfront
            # and slice the upload at the exact boundary the recipient SW
            # will decrypt against (one S3 part = one crypto chunk).
            "TRANSFER_CHUNK_SIZE": settings.TRANSFER_CHUNK_SIZE,
            "SCAN_MAX_FILE_SIZE": settings.SCAN_MAX_FILE_SIZE,
            "TRANSFER_EXPIRY_CHOICES": settings.TRANSFER_EXPIRY_CHOICES,
            "TRANSFER_DEFAULT_EXPIRY_DAYS": settings.TRANSFER_DEFAULT_EXPIRY_DAYS,
            "HELP_URL": getattr(settings, "HELP_URL", ""),
        }

        # Surface Drive picker config only when DRIVE_BASE_URL is set —
        # keeps the "Attach from Drive" button hidden on instances that
        # didn't opt in.
        drive_config = getattr(settings, "DRIVE_CONFIG", None) or {}
        if drive_config.get("base_url"):
            payload["DRIVE"] = {
                "base_url": drive_config["base_url"],
                "sdk_url": drive_config.get("sdk_url", "/sdk"),
                "api_url": drive_config.get("api_url", "/api/v1.0"),
                "app_name": drive_config.get("app_name", "Drive"),
            }

        # Surface the LaGaufre widget only when both URLs are configured —
        # keeps the app switcher, and the third-party script it loads, off
        # instances that didn't opt in.
        lagaufre_config = getattr(settings, "LAGAUFRE_CONFIG", None) or {}
        if lagaufre_config.get("widget_url") and lagaufre_config.get("api_url"):
            payload["LAGAUFRE"] = {
                "widget_url": lagaufre_config["widget_url"],
                "api_url": lagaufre_config["api_url"],
            }

        return drf.response.Response(payload)
