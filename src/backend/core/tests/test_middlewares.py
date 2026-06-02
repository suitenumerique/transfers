"""Tests for ``core.middlewares``."""

from unittest.mock import MagicMock

from django.test import RequestFactory

from core.middlewares import XForwardedForMiddleware


def _run(request):
    """Run the middleware on ``request`` and return the (possibly mutated) request."""
    get_response = MagicMock(return_value="ok")
    middleware = XForwardedForMiddleware(get_response=get_response)
    middleware(request)
    return request


def test_no_xff_header_leaves_remote_addr_untouched():
    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    _run(request)
    assert request.META["REMOTE_ADDR"] == "127.0.0.1"


def test_single_xff_entry_replaces_remote_addr():
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.10")
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    _run(request)
    assert request.META["REMOTE_ADDR"] == "203.0.113.10"


def test_multiple_xff_entries_takes_rightmost():
    # The leftmost entry is whatever the client sent (potentially spoofed);
    # the rightmost is the IP appended by our trusted edge proxy.
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="10.0.0.171, 203.0.113.10"
    )
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    _run(request)
    assert request.META["REMOTE_ADDR"] == "203.0.113.10"


def test_xff_entries_are_stripped():
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="10.0.0.171,   203.0.113.10  "
    )
    _run(request)
    assert request.META["REMOTE_ADDR"] == "203.0.113.10"
