"""Unit tests for the RFC 6266 Content-Disposition builder.

A user-supplied filename must not be able to break out of the
``filename="…"`` token and spoof the saved name (CWE-content-disposition).
"""

from core.services.s3 import _content_disposition


def test_plain_ascii_filename():
    value = _content_disposition("report.pdf")
    assert value == "attachment; filename=\"report.pdf\"; filename*=UTF-8''report.pdf"


def test_quote_injection_is_neutralised():
    # The classic spoof: a quote + a second filename token. Stripping the
    # quote means the injected text stays *inside* the single quoted token
    # instead of breaking out to start a second one.
    value = _content_disposition('report.pdf"; filename=invoice.exe')
    ascii_token = value.split("; filename*=")[0]
    assert ascii_token.startswith('attachment; filename="')
    assert ascii_token.endswith('"')
    assert ascii_token.count('"') == 2  # only the wrapping quotes — no break-out


def test_non_ascii_goes_to_filename_star():
    value = _content_disposition("rapport-éàç.pdf")
    # Non-ASCII bytes are percent-encoded in filename*, never raw in the header.
    assert "filename*=UTF-8''" in value
    assert "%C3%A9" in value  # é
    assert "éàç" not in value


def test_empty_after_sanitisation_falls_back():
    # A name made entirely of stripped chars must still yield a usable token.
    value = _content_disposition('"')
    assert 'filename="download"' in value
