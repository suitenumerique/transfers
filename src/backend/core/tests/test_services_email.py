"""Branding of the notification emails is deployment-supplied — nothing
institutional ships with the code. These tests pin that contract on
``_common_context`` so a refactor can't quietly reintroduce a hardcoded
state mark or a broken ``<img>`` when the operator configured nothing."""

import json
from unittest import mock

from django.test import override_settings

import pytest

from core.services import email as email_service
from core.services.email import _common_context, _footer_logos


@override_settings(EMAIL_LOGO_IMG="", EMAIL_FOOTER_LOGOS="[]", TERMS_URL="")
def test_common_context_neutral_defaults():
    """Unconfigured instance: the shipped product wordmark in the header at
    its native box, and NO footer logo — an empty list, not a list of
    empty URLs, so the template renders no <img> at all."""
    ctx = _common_context("https://example.org")

    assert ctx["logo_url"] == "https://example.org/images/transferts-logo.png"
    assert ctx["logo_width"] == 238
    assert ctx["footer_logos"] == []
    assert ctx["terms_url"] == ""


@override_settings(EMAIL_LOGO_IMG="https://cdn.example.org/wordmark.png")
def test_common_context_custom_header_logo_drops_fixed_width():
    """A custom logo has an unknown ratio: the template must not force the
    238px width tuned for the shipped asset, only the 40px height."""
    ctx = _common_context("https://example.org")

    assert ctx["logo_url"] == "https://cdn.example.org/wordmark.png"
    assert ctx["logo_width"] is None


@override_settings(
    EMAIL_FOOTER_LOGOS=json.dumps(
        [
            {
                "url": "https://cdn.example.org/rf.png",
                "alt": "République Française",
                "width": 80,
                "height": 44,
            },
            {"url": "https://cdn.example.org/org.png", "alt": "My org"},
            {"alt": "no url — must be dropped"},
            "not-a-dict",
        ]
    )
)
def test_footer_logos_parses_entries_and_drops_invalid_ones():
    logos = _footer_logos()

    assert logos == [
        {
            "url": "https://cdn.example.org/rf.png",
            "alt": "République Française",
            "width": 80,
            "height": 44,
        },
        {
            "url": "https://cdn.example.org/org.png",
            "alt": "My org",
            "width": None,
            "height": None,
        },
    ]


@pytest.mark.parametrize(
    ("raw", "warns"),
    [("not json", True), ('{"url": "x"}', True), ("", False), (None, False)],
)
def test_footer_logos_tolerates_bad_config(raw, warns):
    """A branding typo must never block notification delivery: malformed or
    wrongly-shaped config yields no logo (and a warning), not an exception.

    The warning is asserted on the module logger directly rather than via
    ``caplog``: the project's ``core`` logger has ``propagate=False``, so
    records never reach the root handler caplog listens on."""
    with (
        override_settings(EMAIL_FOOTER_LOGOS=raw),
        mock.patch.object(email_service.logger, "warning") as warning,
    ):
        assert _footer_logos() == []
    assert warning.called is warns
    if warns:
        assert "EMAIL_FOOTER_LOGOS" in warning.call_args.args[0]
