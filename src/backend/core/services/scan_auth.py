"""EdDSA-signed request tokens for the file-scanner service.

The file-scanner requires a short-lived Ed25519 JWT on every scan submit; the
token binds the request (method + target + JSON body hash) so a leaked token
cannot be replayed against a different endpoint. Symmetric on the scanner
side: it stores our public key under ``JWT_ISSUER_KEYS[settings.SCAN_JWT_ISSUER]``,
and verifies each incoming call against that.

Wire format matches what the scanner's ``deploy/scripts/mint-token.py`` emits
byte-for-byte: alg = EdDSA, claims iss/aud/iat/exp/htm/htu, plus bh
(base64url SHA-256 of the request body) on POSTs. No caching — mint one per
request so the ttl actually caps replay.
"""

import base64
import hashlib
import time

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings


def _load_signing_key() -> Ed25519PrivateKey:
    """Decode the URL-safe base64 private key from settings into an Ed25519 key.

    ``SCAN_JWT_PRIVATE_KEY`` is the 32 raw private bytes as unpadded URL-safe
    base64 — exactly what the scanner's ``new-issuer.py`` prints.
    """
    fragment = settings.SCAN_JWT_PRIVATE_KEY
    if not fragment:
        raise RuntimeError(
            "SCAN_JWT_PRIVATE_KEY is unset — cannot authenticate to the scanner."
        )
    padding = "=" * (-len(fragment) % 4)
    raw = base64.urlsafe_b64decode(fragment + padding)
    return Ed25519PrivateKey.from_private_bytes(raw)


def mint_request_token(method: str, htu: str, body: bytes | None = None) -> str:
    """Mint a request-bound Bearer JWT for one call to the file-scanner.

    ``htu`` is the request target the scanner will see — ``path`` plus
    ``?query`` if any, no scheme or host. ``body`` (raw bytes to be POSTed)
    binds the ``bh`` claim on the async endpoint so an intercepted token
    cannot be replayed with a substituted URL / webhook_url. Omit for GET.
    """
    now = int(time.time())
    payload = {
        "iss": settings.SCAN_JWT_ISSUER,
        "aud": settings.SCAN_JWT_AUDIENCE,
        "iat": now,
        "exp": now + settings.SCAN_JWT_TTL,
        "htm": method.upper(),
        "htu": htu,
    }
    if body is not None:
        digest = hashlib.sha256(body).digest()
        payload["bh"] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return jwt.encode(payload, _load_signing_key(), algorithm="EdDSA")
