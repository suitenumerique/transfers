"""Tests for the public config endpoint."""

from unittest.mock import patch

import pytest

CONFIG_URL = "/api/v1.0/config/"


@pytest.mark.django_db
class TestConfigView:
    """GET /api/v1.0/config/ — public settings for the frontend."""

    def test_drive_absent_when_base_url_empty(self, api_client):
        """DRIVE key must not appear when DRIVE_BASE_URL is unset."""
        with patch.dict("os.environ", {"DRIVE_BASE_URL": ""}, clear=False):
            response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "DRIVE" not in response.data

    def test_drive_present_when_base_url_set(self, api_client):
        """DRIVE key must appear with the right shape when DRIVE_BASE_URL is set."""
        with patch.dict(
            "os.environ",
            {
                "DRIVE_BASE_URL": "https://drive.example.gouv.fr",
                "DRIVE_SDK_URL": "/sdk",
                "DRIVE_API_URL": "/api/v1.0",
                "DRIVE_APP_NAME": "Drive",
            },
            clear=False,
        ):
            # DRIVE_CONFIG is read from os.environ at class-definition time,
            # so we also need to patch the resolved setting dict.
            drive_config = {
                "base_url": "https://drive.example.gouv.fr",
                "sdk_url": "/sdk",
                "api_url": "/api/v1.0",
                "app_name": "Drive",
            }
            with patch("core.api.viewsets.config.settings") as mock_settings:
                # Forward all standard attributes from real settings, then
                # override DRIVE_CONFIG.
                from django.conf import settings as real_settings

                mock_settings.TRANSFER_MAX_FILE_SIZE = real_settings.TRANSFER_MAX_FILE_SIZE
                mock_settings.TRANSFER_MAX_TOTAL_SIZE = real_settings.TRANSFER_MAX_TOTAL_SIZE
                mock_settings.TRANSFER_MAX_FILES_PER_TRANSFER = (
                    real_settings.TRANSFER_MAX_FILES_PER_TRANSFER
                )
                mock_settings.TRANSFER_EXPIRY_CHOICES = real_settings.TRANSFER_EXPIRY_CHOICES
                mock_settings.TRANSFER_DEFAULT_EXPIRY_DAYS = (
                    real_settings.TRANSFER_DEFAULT_EXPIRY_DAYS
                )
                mock_settings.DRIVE_CONFIG = drive_config

                response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "DRIVE" in response.data
        assert response.data["DRIVE"] == {
            "base_url": "https://drive.example.gouv.fr",
            "sdk_url": "/sdk",
            "api_url": "/api/v1.0",
            "app_name": "Drive",
        }

    def test_returns_transfer_limits(self, api_client):
        """Config must always include transfer limit settings."""
        response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "TRANSFER_MAX_FILE_SIZE" in response.data
        assert "TRANSFER_MAX_TOTAL_SIZE" in response.data
        assert "TRANSFER_MAX_FILES_PER_TRANSFER" in response.data
