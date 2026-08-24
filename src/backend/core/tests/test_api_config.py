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

    def test_lagaufre_absent_when_urls_empty(self, api_client):
        """LAGAUFRE must not appear when the widget isn't configured.

        Off by default: an instance outside a Suite deployment must not pull
        the third-party widget script nor list another operator's services.
        """
        with patch(
            "core.api.viewsets.config.settings.LAGAUFRE_CONFIG",
            {"widget_url": "", "api_url": ""},
        ):
            response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "LAGAUFRE" not in response.data

    def test_lagaufre_absent_when_only_one_url_set(self, api_client):
        """A half-configured widget must stay hidden rather than render broken."""
        with patch(
            "core.api.viewsets.config.settings.LAGAUFRE_CONFIG",
            {"widget_url": "https://static.example.gouv.fr/lagaufre.js", "api_url": ""},
        ):
            response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "LAGAUFRE" not in response.data

    def test_lagaufre_present_when_both_urls_set(self, api_client):
        """LAGAUFRE key must appear with both URLs when configured."""
        lagaufre_config = {
            "widget_url": "https://static.example.gouv.fr/lagaufre.js",
            "api_url": "https://operateurs.example.gouv.fr/api/v1.0/lagaufre/services/",
        }
        with patch(
            "core.api.viewsets.config.settings.LAGAUFRE_CONFIG",
            lagaufre_config,
        ):
            response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert response.data["LAGAUFRE"] == lagaufre_config

    def test_returns_transfer_limits(self, api_client):
        """Config must always include transfer limit settings."""
        response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert "TRANSFER_MAX_FILE_SIZE" in response.data
        assert "TRANSFER_MAX_TOTAL_SIZE" in response.data
        assert "TRANSFER_MAX_FILES_PER_TRANSFER" in response.data
        # The chunk size is the canonical value the recipient SW will
        # use; the frontend reads it here so the encrypted upload it
        # builds matches what the decrypt path expects.
        assert "TRANSFER_CHUNK_SIZE" in response.data
