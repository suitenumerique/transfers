"""Server-side AES-256-GCM chunk encryption for Drive imports.

Mirrors the browser's ``encryption.ts`` byte-for-byte so a chunk we encrypt
here decrypts in the recipient's Service Worker with the same key. Only the
Drive-import path uses this: browser uploads are encrypted client-side and
we never see their plaintext. A Drive import happens server-side (the bytes
are fetched from a permalink), so the backend encrypts them here with the
transfer key before they land in S3.

Layout per crypto chunk, identical to the frontend:

    [ IV (12 bytes) | ciphertext (N bytes) | GCM tag (16 bytes) ]

The AAD binds each chunk to ``f"{file_id}:{part_number}"`` (1-based part
number), exactly as ``encryption.aadForChunk`` and the SW's ``decryptStream``
do, so a tampered storage layer cannot swap or reorder chunks.
"""

import base64
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

IV_BYTES = 12
GCM_TAG_BYTES = 16
KEY_BYTES = 32  # AES-256
# IV + tag added on top of every chunk's plaintext. Matches
# ``CRYPTO_OVERHEAD_PER_CHUNK`` on the frontend and in serializers.
OVERHEAD_PER_CHUNK = IV_BYTES + GCM_TAG_BYTES

# URL-safe base64 alphabet, optional padding. Mirrors the serializer's
# ``_ENCRYPTION_KEY_RE`` — the fragment travels in a URL, so '+' and '/' are
# not acceptable even though they are valid standard base64.
_FRAGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def decode_key(fragment: str) -> bytes:
    """Decode the URL-safe base64 key fragment into raw AES-256 key bytes.

    Accepts the frontend's unpadded 43-char form as well as the padded
    44-char form.
    """
    # Check the alphabet up front: ``urlsafe_b64decode`` silently discards junk
    # characters, and passing ``altchars`` to ``b64decode`` would still accept
    # the standard '+' and '/'. Neither belongs in a URL fragment, and both
    # would otherwise decode to a key we'd happily use.
    if not _FRAGMENT_RE.match(fragment or ""):
        raise ValueError("Key fragment must be URL-safe base64 (A-Z a-z 0-9 - _).")
    padding = "=" * (-len(fragment) % 4)
    raw = base64.urlsafe_b64decode(fragment + padding)
    if len(raw) != KEY_BYTES:
        raise ValueError(f"Expected a {KEY_BYTES}-byte key, got {len(raw)}.")
    return raw


def encrypt_chunk(
    key: bytes, plaintext: bytes, file_id: str, part_number: int
) -> bytes:
    """Encrypt one plaintext chunk into ``IV || ciphertext || tag``.

    ``AESGCM.encrypt`` returns the ciphertext with the 16-byte tag already
    appended, matching WebCrypto's ``subtle.encrypt`` output, so we just
    prepend a fresh random IV.
    """
    iv = os.urandom(IV_BYTES)
    aad = f"{file_id}:{part_number}".encode()
    ct = AESGCM(key).encrypt(iv, plaintext, aad)
    return iv + ct
