"""Tests for the file-scanner JWT minting helper.

Round-trips the token against the scanner's own verifier semantics (alg,
required claims, request-binding) using pyjwt so a wire-format regression
here shows up before the smoke test does.
"""

import base64
import hashlib

import pytest

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from core.services import scan_auth


def _keypair() -> tuple[str, str]:
    """Fresh Ed25519 keypair as unpadded base64url — the wire format the
    scanner's ``deploy/scripts/new-issuer.py`` emits."""
    key = Ed25519PrivateKey.generate()
    private = base64.urlsafe_b64encode(
        key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    ).rstrip(b"=").decode()
    public = base64.urlsafe_b64encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).rstrip(b"=").decode()
    return private, public


@pytest.fixture
def signing_setup(settings):
    """Populate the settings the helper reads, return the matching pubkey."""
    private, public = _keypair()
    settings.SCAN_JWT_PRIVATE_KEY = private
    settings.SCAN_JWT_ISSUER = "test-caller"
    settings.SCAN_JWT_AUDIENCE = "file-scanner"
    settings.SCAN_JWT_TTL = 300
    return public


def _verify(token: str, public_key: str) -> dict:
    """Verify with pyjwt — same alg/audience the scanner uses."""
    raw_pub = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pub = Ed25519PublicKey.from_public_bytes(raw_pub)
    return jwt.decode(token, pub, algorithms=["EdDSA"], audience="file-scanner")


def test_mint_carries_expected_claims(signing_setup):
    """Minimal happy path: iss/aud/htm/htu land as configured."""
    public = signing_setup
    token = scan_auth.mint_request_token("POST", "/api/v1.0/scan-async")
    claims = _verify(token, public)
    assert claims["iss"] == "test-caller"
    assert claims["aud"] == "file-scanner"
    assert claims["htm"] == "POST"
    assert claims["htu"] == "/api/v1.0/scan-async"


def test_mint_binds_body_hash_when_body_is_given(signing_setup):
    """``bh`` = base64url SHA-256 of the raw body bytes, matching what the
    scanner recomputes on the receiving side. A body change ⇒ mismatch ⇒ the
    scanner rejects the token."""
    public = signing_setup
    body = b'{"url":"http://s/x","filename":"f"}'
    token = scan_auth.mint_request_token(
        "POST", "/api/v1.0/scan-async", body=body
    )
    claims = _verify(token, public)
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
    )
    assert claims["bh"] == expected


def test_mint_omits_body_hash_when_no_body(signing_setup):
    """GETs and other body-less requests omit ``bh`` — the scanner's binding
    check for the sync ``/scan`` endpoint doesn't require it."""
    public = signing_setup
    token = scan_auth.mint_request_token("GET", "/check")
    claims = _verify(token, public)
    assert "bh" not in claims


def test_mint_uses_eddsa_algorithm(signing_setup):
    """The scanner accepts EdDSA only. A regression to HS256 (a stray dev
    tweak) would silently sign with a symmetric alg and be rejected."""
    token = scan_auth.mint_request_token("POST", "/api/v1.0/scan-async")
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "EdDSA"


def test_mint_without_key_raises(settings):
    """A stack that runs with scanning enabled but no signing key should
    surface a clear error instead of a cryptography traceback."""
    settings.SCAN_JWT_PRIVATE_KEY = ""
    with pytest.raises(RuntimeError, match="SCAN_JWT_PRIVATE_KEY"):
        scan_auth.mint_request_token("POST", "/api/v1.0/scan-async")


def test_mint_accepts_padded_or_unpadded_key(signing_setup):
    """The scanner's ``new-issuer.py`` prints unpadded base64url; be tolerant
    of an operator adding ``=`` padding by hand and still work."""
    padded = signing_setup + "="
    # signing_setup put the unpadded pub in scanner; the private key in
    # settings should stay decodable either way.
    private = base64.urlsafe_b64encode(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
    ).decode()
    from django.conf import settings as django_settings

    django_settings.SCAN_JWT_PRIVATE_KEY = private  # 44 chars, padded
    # Should not raise:
    scan_auth.mint_request_token("POST", "/x")
    assert padded  # keeps the fixture value in scope
