// @vitest-environment node
//
// Round-trip checks for the E2E crypto module. Targets the contract the
// recipient's Service Worker relies on: encrypt(plaintext) → decrypt →
// identical bytes, size math matches what we declare to the backend.
//
// Runs under the node env (not the project's default jsdom) — Node 16+
// exposes the standard WebCrypto on `globalThis.crypto`, which is all we
// need. No mocking; a regression in IV layout, tag handling, or chunk size
// accounting fails here.

import { describe, expect, it } from "vitest";

import {
  CRYPTO_OVERHEAD_PER_CHUNK,
  base64UrlDecode,
  base64UrlEncode,
  ciphertextSize,
  decryptChunk,
  encryptChunk,
  generateTransferKey,
  importTransferKey,
} from "./e2eCrypto";

describe("e2eCrypto", () => {
  it("encrypts and decrypts a chunk back to the original plaintext", async () => {
    const { cryptoKey } = await generateTransferKey();
    const plain = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    const ct = await encryptChunk(cryptoKey, plain);
    const dec = await decryptChunk(cryptoKey, ct);
    expect(Array.from(dec)).toEqual(Array.from(plain));
  });

  it("produces ciphertext exactly OVERHEAD bytes larger than plaintext", async () => {
    const { cryptoKey } = await generateTransferKey();
    const plain = new Uint8Array(1024);
    const ct = await encryptChunk(cryptoKey, plain);
    expect(ct.length).toBe(plain.length + CRYPTO_OVERHEAD_PER_CHUNK);
  });

  it("uses a fresh IV per call so identical plaintext gives different ciphertext", async () => {
    const { cryptoKey } = await generateTransferKey();
    const plain = new Uint8Array(64);
    const a = await encryptChunk(cryptoKey, plain);
    const b = await encryptChunk(cryptoKey, plain);
    expect(Array.from(a)).not.toEqual(Array.from(b));
  });

  it("rejects a ciphertext whose tag was tampered with", async () => {
    const { cryptoKey } = await generateTransferKey();
    const plain = new Uint8Array([1, 2, 3]);
    const ct = await encryptChunk(cryptoKey, plain);
    ct[ct.length - 1] ^= 1; // flip a bit in the tag
    await expect(decryptChunk(cryptoKey, ct)).rejects.toBeDefined();
  });

  it("imports an exported key fragment and decrypts what it encrypted", async () => {
    const { cryptoKey, fragment } = await generateTransferKey();
    const plain = new Uint8Array([42, 43, 44]);
    const ct = await encryptChunk(cryptoKey, plain);

    // Recipient flow: rebuild the key from the URL fragment.
    const recovered = await importTransferKey(fragment);
    const dec = await decryptChunk(recovered, ct);
    expect(Array.from(dec)).toEqual(Array.from(plain));
  });

  it("ciphertextSize counts one overhead per chunk including the last partial one", () => {
    const chunk = 1024;
    // Exact multiple: 3 chunks
    expect(ciphertextSize(3 * chunk, chunk)).toBe(
      3 * chunk + 3 * CRYPTO_OVERHEAD_PER_CHUNK,
    );
    // Off-by-one: 3 full chunks + 1-byte tail = 4 chunks of overhead
    expect(ciphertextSize(3 * chunk + 1, chunk)).toBe(
      3 * chunk + 1 + 4 * CRYPTO_OVERHEAD_PER_CHUNK,
    );
  });

  it("base64UrlEncode/Decode round-trips arbitrary bytes", () => {
    const bytes = new Uint8Array(64);
    for (let i = 0; i < bytes.length; i++) bytes[i] = (i * 31) & 0xff;
    const s = base64UrlEncode(bytes);
    // URL-safe alphabet only.
    expect(/^[A-Za-z0-9_-]+$/.test(s)).toBe(true);
    const back = base64UrlDecode(s);
    expect(Array.from(back)).toEqual(Array.from(bytes));
  });
});
