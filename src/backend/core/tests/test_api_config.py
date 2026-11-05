"""Tests for the public config endpoint."""

import json
from unittest.mock import patch

import pytest

CONFIG_URL = "/api/v1.0/config/"
BRAND_500 = "--c--globals--colors--brand-500"


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

    @pytest.mark.parametrize("enabled", [True, False])
    def test_confidential_flag_follows_setting(self, api_client, settings, enabled):
        """The form hides the confidential toggle from this flag alone, so it
        must mirror the setting exactly (not just default to True)."""
        settings.TRANSFER_CONFIDENTIAL_ENABLED = enabled

        response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert response.data["TRANSFER_CONFIDENTIAL_ENABLED"] is enabled

    def test_branding_defaults_are_neutral(self, api_client, settings):
        """An instance that configures nothing must advertise no operator.

        This is what used to be compiled in: the theme was hard-wired to
        ``anct-light``, the ProConnect button always rendered and "Learn more"
        always pointed at La Suite territoriale. A default install has to come
        out branding-free.
        """
        settings.FRONTEND_THEME = None
        settings.THEME_CUSTOMIZATION_FILE_PATH = ""
        settings.DEFAULT_CONFIG = ""

        response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        # Empty, not "anct-light": the frontend maps this to the neutral theme.
        assert response.data["FRONTEND_THEME"] == ""
        assert response.data["theme_customization"] == {}

    def test_theme_comes_from_default_config(self, api_client, settings):
        """The base configuration lands under the key ``docs`` already uses."""
        settings.DEFAULT_CONFIG = json.dumps(
            {
                "theme_customization": {
                    "help": {"documentation_url": "https://help.example.test"}
                }
            }
        )

        response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert response.data["theme_customization"] == {
            "help": {"documentation_url": "https://help.example.test"}
        }

    def test_theme_resolves_per_domain(self, api_client, settings):
        """Two domains, two themes, one image — the point of the exercise."""
        settings.ALLOWED_HOSTS = ["testserver", "opsn1.test"]
        settings.DEFAULT_CONFIG = json.dumps(
            {"theme_customization": {"colors": {BRAND_500: "#6969DF"}}}
        )
        settings.CONFIG_OVERRIDES = json.dumps(
            {"opsn1.test": {"theme_customization": {"colors": {BRAND_500: "#C83F49"}}}}
        )

        base = api_client.get(CONFIG_URL)
        matched = api_client.get(CONFIG_URL, HTTP_HOST="opsn1.test")

        assert base.data["theme_customization"]["colors"] == {BRAND_500: "#6969DF"}
        assert matched.data["theme_customization"]["colors"] == {BRAND_500: "#C83F49"}

    def test_port_is_ignored(self, api_client, settings):
        """An override key is a domain, not an origin: dev runs on a port."""
        settings.ALLOWED_HOSTS = ["testserver", "opsn1.test"]
        settings.CONFIG_OVERRIDES = json.dumps(
            {"opsn1.test": {"theme_customization": {"fontFamily": "Inter"}}}
        )

        response = api_client.get(CONFIG_URL, HTTP_HOST="opsn1.test:8980")

        assert response.data["theme_customization"]["fontFamily"] == "Inter"

    def test_an_unmatched_domain_gets_the_base(self, api_client, settings):
        """Most instances serve one domain and configure no override at all."""
        settings.ALLOWED_HOSTS = ["testserver", "opsn1.test"]
        settings.DEFAULT_CONFIG = json.dumps(
            {"theme_customization": {"fontFamily": "Inter"}}
        )
        settings.CONFIG_OVERRIDES = json.dumps(
            {"opsn1.test": {"theme_customization": {"fontFamily": "Georgia"}}}
        )

        response = api_client.get(CONFIG_URL)

        assert response.data["theme_customization"]["fontFamily"] == "Inter"

    def test_override_merges_onto_base(self, api_client, settings):
        """An override states what differs, not a whole theme.

        A deployment adding a domain shouldn't have to restate every key, so
        the override merges key by key — and its lists replace rather than
        concatenate, which is the only way to *remove* a link.
        """
        settings.ALLOWED_HOSTS = ["testserver", "opsn1.test"]
        settings.DEFAULT_CONFIG = json.dumps(
            {
                "theme_customization": {
                    "help": {
                        "documentation_url": "https://help.example.test",
                        "support_url": "https://support.example.test",
                    },
                    "footer": {
                        "default": {"externalLinks": [{"label": "a", "href": "#a"}]}
                    },
                }
            }
        )
        settings.CONFIG_OVERRIDES = json.dumps(
            {
                "opsn1.test": {
                    "theme_customization": {
                        "help": {"support_url": "https://support.opsn1.test"},
                        "footer": {
                            "default": {"externalLinks": [{"label": "b", "href": "#b"}]}
                        },
                    }
                }
            }
        )

        theme = api_client.get(CONFIG_URL, HTTP_HOST="opsn1.test").data[
            "theme_customization"
        ]

        # Untouched key survives, touched key wins, list replaces wholesale.
        assert theme["help"]["documentation_url"] == "https://help.example.test"
        assert theme["help"]["support_url"] == "https://support.opsn1.test"
        assert theme["footer"]["default"]["externalLinks"] == [
            {"label": "b", "href": "#b"}
        ]

    def test_unknown_theme_keys_travel_through(self, api_client, settings):
        """A key this build doesn't know must reach the browser untouched.

        ``docs`` guarantees the same thing for its own theme file, and it is
        what lets the products converge on one shared file without each of
        them having to know every key in it.
        """
        settings.DEFAULT_CONFIG = json.dumps(
            {
                "theme_customization": {
                    "onboarding": {"ready_template_url": "https://example.test/t"}
                }
            }
        )

        response = api_client.get(CONFIG_URL)

        assert response.data["theme_customization"]["onboarding"] == {
            "ready_template_url": "https://example.test/t"
        }

    def test_unknown_section_is_never_served(self, api_client, settings):
        """A section this build doesn't know stays server-side.

        The resolver will carry non-public sections one day — per-domain
        authentication, for one. Not knowing what a section holds is reason
        enough never to hand it to a browser.
        """
        settings.DEFAULT_CONFIG = json.dumps(
            {
                "theme_customization": {"fontFamily": "Inter"},
                "auth": {"client_secret": "must-not-leak"},
            }
        )

        response = api_client.get(CONFIG_URL)

        assert response.data["theme_customization"] == {"fontFamily": "Inter"}
        assert "auth" not in response.data
        assert "must-not-leak" not in response.content.decode()

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
        # The scan wait budget must reach the frontend so its poller and the
        # backend's rescan/reaper agree on how long a big scan may run.
        assert response.data["SCAN_WAIT_BASE_SECONDS"] > 0
        assert response.data["SCAN_WAIT_SECONDS_PER_GIB"] > 0

    @pytest.mark.parametrize("url", ["", "https://support.example.gouv.fr/"])
    def test_support_url_follows_setting(self, api_client, settings, url):
        """The error page shows its support link only when this is non-empty."""
        settings.SUPPORT_URL = url

        response = api_client.get(CONFIG_URL)

        assert response.status_code == 200
        assert response.data["SUPPORT_URL"] == url
