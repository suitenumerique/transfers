"""Tests for the public config endpoint."""

from unittest.mock import patch

import pytest

CONFIG_URL = "/api/v1.0/config/"


@pytest.mark.django_db
class TestConfigView:
    """GET /api/v1.0/config/ — public settings for the frontend."""

    def test_drive_absent_when_base_url_empty(self, api_client):
        """DRIVE key must not appear when DRIVE_BASE_URL is unset.

        ``DRIVE_CONFIG`` is resolved at settings-module import time, so
        patching ``os.environ`` here would be too late. Stub the attribute
        on the viewset's already-bound ``settings`` module instead.
        """
        with patch(
            "core.api.viewsets.config.settings.DRIVE_CONFIG",
            {"base_url": ""},
        ):
            response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "DRIVE" not in response.data

    def test_drive_present_when_base_url_set(self, api_client):
        """DRIVE key must appear with the right shape when DRIVE_BASE_URL is set.

        Patch only the one dict we need to override, not the whole settings
        module — replacing the module reference with a MagicMock exposed
        every *other* setting as an auto-generated MagicMock child, which
        cascaded into OOM when DRF's renderer walked the response.
        """
        drive_config = {
            "base_url": "https://drive.example.gouv.fr",
            "sdk_url": "/sdk",
            "api_url": "/api/v1.0",
            "app_name": "Drive",
        }
        with patch(
            "core.api.viewsets.config.settings.DRIVE_CONFIG",
            drive_config,
        ):
            response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "DRIVE" in response.data
        assert response.data["DRIVE"] == drive_config

    def test_returns_transfer_limits(self, api_client):
        """Config must always include transfer limit settings."""
        response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "TRANSFER_MAX_FILE_SIZE" in response.data
        assert "TRANSFER_MAX_TOTAL_SIZE" in response.data
        assert "TRANSFER_MAX_FILES_PER_TRANSFER" in response.data
