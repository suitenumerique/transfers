"""Unit tests for ``core.services.encryption`` — the server-side chunk
encryption used by Drive imports. The layout must match the browser's
``e2eCrypto.ts`` so a chunk encrypted here decrypts in the recipient SW."""

import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import pytest

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


class TestEncryptChunk:
    def test_layout_is_iv_ciphertext_tag(self):
        key = bytes(32)
        plaintext = b"hello world"
        out = encryption.encrypt_chunk(key, plaintext, "file-1", 1)
        # 12-byte IV + ciphertext (== plaintext length) + 16-byte tag.
        assert len(out) == encryption.IV_BYTES + len(plaintext) + encryption.GCM_TAG_BYTES

    def test_round_trips_with_matching_aad(self):
        # Decrypt exactly the way the recipient SW does: split off the IV,
        # then AES-GCM decrypt the rest with AAD "fileId:partNumber".
        key = bytes(range(32))
        plaintext = b"some confidential bytes"
        file_id, part = "abc-123", 4
        out = encryption.encrypt_chunk(key, plaintext, file_id, part)

        iv = out[: encryption.IV_BYTES]
        body = out[encryption.IV_BYTES :]
        aad = f"{file_id}:{part}".encode()
        assert AESGCM(key).decrypt(iv, body, aad) == plaintext

    def test_wrong_part_number_fails_authentication(self):
        from cryptography.exceptions import InvalidTag

        key = bytes(range(32))
        out = encryption.encrypt_chunk(key, b"payload", "abc-123", 1)
        iv = out[: encryption.IV_BYTES]
        body = out[encryption.IV_BYTES :]
        # AAD bound to part 1; verifying against part 2 must fail, which is
        # what stops a storage layer from reordering chunks.
        with pytest.raises(InvalidTag):
            AESGCM(key).decrypt(iv, body, b"abc-123:2")

    def test_fresh_iv_per_call(self):
        key = bytes(32)
        a = encryption.encrypt_chunk(key, b"same", "f", 1)
        b = encryption.encrypt_chunk(key, b"same", "f", 1)
        # Random IV each time ⇒ different ciphertext for identical input.
        assert a != b
