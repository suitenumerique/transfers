"""Unit tests for ``core.services.encryption`` — the server-side chunk
encryption used by Drive imports. The layout must match the browser's
``encryption.ts`` so a chunk encrypted here decrypts in the recipient SW."""

import base64

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.services import encryption


def _key_fragment(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class TestDecodeKey:
    def test_decodes_unpadded_43_char_fragment(self):
        raw = bytes(range(32))
        fragment = _key_fragment(raw)  # 43 chars, no padding
        assert len(fragment) == 43
        assert encryption.decode_key(fragment) == raw

    def test_accepts_padded_form(self):
        raw = bytes(range(32))
        padded = base64.urlsafe_b64encode(raw).decode()  # 44 chars with '='
        assert encryption.decode_key(padded) == raw

    def test_rejects_wrong_length(self):
        short = _key_fragment(bytes(16))
        with pytest.raises(ValueError):
            encryption.decode_key(short)

    def test_rejects_malformed_base64(self):
        # Junk outside the URL-safe alphabet must raise, not be silently
        # stripped down to a wrong-length (or coincidentally valid) key.
        with pytest.raises(ValueError):
            encryption.decode_key("!!!!" + "A" * 39)
        with pytest.raises(ValueError):
            encryption.decode_key("not valid base64 @#$%")

    def test_rejects_non_urlsafe_chars_at_valid_length(self):
        # 43 chars — exactly the length of a well-formed fragment — but '+'
        # belongs to the standard alphabet, not the URL-safe one. It must be
        # rejected rather than silently discarded (which would otherwise
        # shorten the input and decode to a bogus key).
        fragment = _key_fragment(bytes(range(32)))
        assert len(fragment) == 43
        malformed = "+" + fragment[1:]
        assert len(malformed) == 43
        with pytest.raises(ValueError):
            encryption.decode_key(malformed)


class TestTotalParts:
    def test_empty_plaintext_still_ships_one_chunk(self):
        # The wire format authenticates every chunk including the trailing
        # empty one for zero-byte plaintext, matching the frontend's
        # ``ciphertextSize(0, N) == CRYPTO_OVERHEAD_PER_CHUNK``.
        assert encryption.total_parts(0, 1024) == 1

    def test_exact_multiple(self):
        assert encryption.total_parts(3 * 1024, 1024) == 3

    def test_partial_last_chunk_rounds_up(self):
        assert encryption.total_parts(3 * 1024 + 1, 1024) == 4


class TestEncryptChunk:
    def test_layout_is_iv_ciphertext_tag(self):
        key = bytes(32)
        plaintext = b"hello world"
        out = encryption.encrypt_chunk(key, plaintext, "file-1", 1, 1)
        # 12-byte IV + ciphertext (== plaintext length) + 16-byte tag.
        assert (
            len(out) == encryption.IV_BYTES + len(plaintext) + encryption.GCM_TAG_BYTES
        )

    def test_round_trips_with_matching_aad(self):
        # Decrypt exactly the way the recipient SW does: split off the IV,
        # then AES-GCM decrypt the rest with AAD "fileId:partNumber:parts".
        key = bytes(range(32))
        plaintext = b"some confidential bytes"
        file_id, part, parts = "abc-123", 4, 7
        out = encryption.encrypt_chunk(key, plaintext, file_id, part, parts)

        iv = out[: encryption.IV_BYTES]
        body = out[encryption.IV_BYTES :]
        aad = f"{file_id}:{part}:{parts}".encode()
        assert AESGCM(key).decrypt(iv, body, aad) == plaintext

    def test_wrong_part_number_fails_authentication(self):
        from cryptography.exceptions import InvalidTag

        key = bytes(range(32))
        out = encryption.encrypt_chunk(key, b"payload", "abc-123", 1, 3)
        iv = out[: encryption.IV_BYTES]
        body = out[encryption.IV_BYTES :]
        # AAD bound to part 1; verifying against part 2 must fail, which is
        # what stops a storage layer from reordering chunks.
        with pytest.raises(InvalidTag):
            AESGCM(key).decrypt(iv, body, b"abc-123:2:3")

    def test_wrong_parts_total_fails_authentication(self):
        # A caller who tries to convince the scanner that only 2 chunks
        # exist (to slip past a truncation check) must not authenticate
        # against a chunk the sender bound to a 3-part total.
        from cryptography.exceptions import InvalidTag

        key = bytes(range(32))
        out = encryption.encrypt_chunk(key, b"payload", "abc-123", 1, 3)
        iv = out[: encryption.IV_BYTES]
        body = out[encryption.IV_BYTES :]
        with pytest.raises(InvalidTag):
            AESGCM(key).decrypt(iv, body, b"abc-123:1:2")

    def test_fresh_iv_per_call(self):
        key = bytes(32)
        a = encryption.encrypt_chunk(key, b"same", "f", 1, 1)
        b = encryption.encrypt_chunk(key, b"same", "f", 1, 1)
        # Random IV each time ⇒ different ciphertext for identical input.
        assert a != b
