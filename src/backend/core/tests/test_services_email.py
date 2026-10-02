"""Branding of the notification emails is deployment-supplied — nothing
institutional ships with the code. These tests pin that contract on
``_common_context`` so a refactor can't quietly reintroduce a hardcoded
state mark or a broken ``<img>`` when the operator configured nothing."""

import json
import re
from unittest import mock

from django.template.loader import render_to_string
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

    assert ctx["logo_url"] == "https://example.org/images/transfers-logo.png"
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


@override_settings(
    EMAIL_FOOTER_LOGOS=json.dumps(
        [
            {"url": "  https://cdn.example.org/padded.png  ", "alt": "padded"},
            {"url": 123, "alt": "not a string"},
            {"url": "   ", "alt": "blank"},
            {"url": "", "alt": "empty"},
        ]
    )
)
def test_footer_logos_requires_a_non_blank_string_url():
    """``url`` must be a real string: a number or whitespace would land
    verbatim in ``src="…"`` as a broken image. Surrounding whitespace is
    normalized away, everything else is dropped — with one warning per
    dropped entry, so a missing logo can be traced back to the config."""
    with mock.patch.object(email_service.logger, "warning") as warning:
        logos = _footer_logos()

    assert [logo["url"] for logo in logos] == ["https://cdn.example.org/padded.png"]
    assert warning.call_count == 3
    for call in warning.call_args_list:
        assert "EMAIL_FOOTER_LOGOS" in call.args[0]
    # Entries are identified by index only — the payload itself isn't logged.
    assert [call.args[1] for call in warning.call_args_list] == [1, 2, 3]


# --- Rendered template -------------------------------------------------------
#
# ``_base.html`` is what every notification inherits; rendering it directly
# with the branding context pins the HTML each configuration produces, so a
# template edit can't quietly bring back a footer <img> on an unconfigured
# instance or force a width on a custom header logo.

FOOTER_MARKER = "Conditions générales d'utilisation"


def _render_base(base_url="https://example.org"):
    return render_to_string(
        "core/emails/_base.html",
        {
            **_common_context(base_url),
            "subject": "Test",
            "banner_label": "Banner",
        },
    )


def _imgs(html):
    """Every <img …> tag in the rendered HTML, in document order."""
    return re.findall(r"<img [^>]*>", html)


@override_settings(EMAIL_LOGO_IMG="", EMAIL_FOOTER_LOGOS="[]", TERMS_URL="")
def test_base_template_renders_no_footer_when_unconfigured():
    html = _render_base()
    imgs = _imgs(html)

    # Header only: the shipped wordmark at its native box.
    assert len(imgs) == 1
    assert 'src="https://example.org/images/transfers-logo.png"' in imgs[0]
    assert 'width="238"' in imgs[0]
    assert 'height="40"' in imgs[0]
    # No divider, no terms link, no footer table at all.
    assert "<hr" not in html
    assert FOOTER_MARKER not in html


@override_settings(
    EMAIL_LOGO_IMG="", EMAIL_FOOTER_LOGOS="[]", TERMS_URL="https://example.org/cgu"
)
def test_base_template_renders_terms_only_footer():
    html = _render_base()

    assert len(_imgs(html)) == 1  # header only, still no footer image
    assert "<hr" in html
    assert 'href="https://example.org/cgu"' in html
    assert FOOTER_MARKER in html


@override_settings(
    EMAIL_LOGO_IMG="",
    EMAIL_FOOTER_LOGOS=json.dumps(
        [
            {
                "url": "https://cdn.example.org/rf.png",
                "alt": "République Française",
                "width": 80,
                "height": 44,
            },
            {"url": "https://cdn.example.org/org.png", "alt": "My org"},
        ]
    ),
    TERMS_URL="https://example.org/cgu",
)
def test_base_template_renders_footer_logos_with_terms():
    html = _render_base()
    imgs = _imgs(html)

    assert len(imgs) == 3  # header + 2 footer logos
    rf, org = imgs[1], imgs[2]
    assert 'src="https://cdn.example.org/rf.png"' in rf
    assert 'alt="République Française"' in rf
    assert 'width="80"' in rf
    assert 'height="44"' in rf
    # No declared size ⇒ no size attributes, the client uses the natural one.
    assert 'src="https://cdn.example.org/org.png"' in org
    assert 'alt="My org"' in org
    assert "width=" not in org
    assert "height=" not in org
    # Last logo hugs the right edge; the terms link sits between.
    assert "margin-left:auto" in org
    assert "<hr" in html
    assert html.index(rf) < html.index(FOOTER_MARKER) < html.index(org)


@override_settings(
    EMAIL_LOGO_IMG="https://cdn.example.org/wordmark.png",
    EMAIL_FOOTER_LOGOS="[]",
    TERMS_URL="",
)
def test_base_template_renders_custom_header_logo_without_width():
    html = _render_base()
    imgs = _imgs(html)

    assert len(imgs) == 1
    assert 'src="https://cdn.example.org/wordmark.png"' in imgs[0]
    assert 'height="40"' in imgs[0]
    assert "width=" not in imgs[0]
    assert "transfers-logo.png" not in html
