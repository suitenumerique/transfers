// Client-side AES-256-GCM helpers for encrypted transfers.
//
// Threat model splits by mode: every transfer is encrypted in the sender's
// browser and S3 stores ciphertext only. In **confidential** mode the key
// is embedded in the download URL fragment (`#k=...`) and never leaves the
// sender's browser until the recipient opens the link — the backend never
// sees it and cannot read the files. In the default (non-confidential)
// mode ``useTransferDraft.submit()`` posts the key to the backend at
// finalize so the download API can serve it to recipients transparently:
// the encryption still protects against an S3-only breach (ciphertext
// without the key) but not against a full backend compromise. See
// ``docs/ENCRYPTION.md`` for the full mode comparison.
//
// Layout per crypto chunk on S3:
//
//     [ IV (12 bytes) | ciphertext (N bytes) | GCM tag (16 bytes) ]
//
// One crypto chunk maps to one S3 multipart part. The chunk size is the
// server-side ``TRANSFER_CHUNK_SIZE`` (surfaced via /api/v1.0/config/);
// the recipient can compute part boundaries from the file's plaintext
// size plus that value, without any out-of-band metadata. The last chunk
// is shorter — same layout, just less plaintext.
//
// IVs are random per chunk: with a 256-bit key the birthday probability of
// an IV collision matters only at ~2^48 chunks, which is unreachable inside
// our 20 GiB / 25 MiB ≈ 800-chunks-per-file budget.

export const CRYPTO_OVERHEAD_PER_CHUNK = 12 /* IV */ + 16 /* GCM tag */;

const KEY_BYTES = 32; // AES-256
const IV_BYTES = 12;

export interface GeneratedKey {
  cryptoKey: CryptoKey;
  // URL-safe base64 representation of the raw 32 random bytes. Stable
  // 43-char string (no padding), safe to drop in a URL fragment.
  fragment: string;
}

// WebCrypto accepts `BufferSource` (ArrayBuffer | ArrayBufferView). Recent
// TS lib.dom.d.ts pins those views to `ArrayBuffer` rather than
// `ArrayBufferLike`, so `crypto.getRandomValues` / `Uint8Array.subarray`
// outputs trip the type checker. The values are always ArrayBuffer-backed
// at runtime — this helper makes that explicit.
function asBufferSource(view: Uint8Array): BufferSource {
  return view as unknown as BufferSource;
}

export async function generateTransferKey(): Promise<GeneratedKey> {
  const raw = crypto.getRandomValues(new Uint8Array(KEY_BYTES));
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    asBufferSource(raw),
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"],
  );
  return { cryptoKey, fragment: base64UrlEncode(raw) };
}

export async function importTransferKey(fragment: string): Promise<CryptoKey> {
  const raw = base64UrlDecode(fragment);
  if (raw.length !== KEY_BYTES) {
    throw new Error("Invalid key length");
  }
  return crypto.subtle.importKey(
    "raw",
    asBufferSource(raw),
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"],
  );
}

// AAD binds a chunk to its (file, position, total) so a tampered storage
// cannot swap chunks between files, reorder them inside a file, or drop
// whole trailing chunks: an attacker who substitutes a valid chunk from a
// different position — or truncates the object at a chunk boundary — sends
// data whose GCM tag no longer verifies against the recipient's AAD. Use
// ``aadForChunk`` to build the same byte sequence on encrypt and decrypt.
// ``parts`` is bound in every chunk (not just the last) so the total is
// authenticated regardless of which chunk gets checked first, and the
// file-scanner service authenticates the same way.
//
// Return type is BufferSource because that's what crypto.subtle wants and
// the same view-vs-ArrayBufferLike incompatibility documented on
// ``asBufferSource`` applies — the cast is purely about TS lib.dom typings,
// the bytes are real ArrayBuffer at runtime.
export function aadForChunk(
  fileId: string,
  partNumber: number,
  parts: number,
): BufferSource {
  const bytes = new TextEncoder().encode(`${fileId}:${partNumber}:${parts}`);
  return bytes as unknown as BufferSource;
}

// Number of chunks the wire format emits for a plaintext of this size.
// Zero-byte plaintext still ships one authenticated (IV + tag only) chunk,
// matching ``ciphertextSize(0, N) === CRYPTO_OVERHEAD_PER_CHUNK`` and the
// backend's ``total_parts``. Used to compute the ``parts`` bound into every
// chunk's AAD, and to fill the ``encryption.parts`` field sent to the
// file-scanner.
export function totalParts(plaintextSize: number, chunkSize: number): number {
  if (plaintextSize <= 0) return 1;
  return Math.ceil(plaintextSize / chunkSize);
}

export async function encryptChunk(
  key: CryptoKey,
  plaintext: BufferSource,
  additionalData: BufferSource,
): Promise<Uint8Array> {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const ct = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: asBufferSource(iv), additionalData },
      key,
      plaintext,
    ),
  );
  // Concatenate IV || ciphertext+tag. WebCrypto returns ciphertext with the
  // 16-byte tag already appended.
  const out = new Uint8Array(iv.length + ct.length);
  out.set(iv, 0);
  out.set(ct, iv.length);
  return out;
}

export async function decryptChunk(
  key: CryptoKey,
  chunk: Uint8Array,
  additionalData: BufferSource,
): Promise<Uint8Array> {
  if (chunk.length < IV_BYTES + 16) {
    throw new Error("Ciphertext chunk too short");
  }
  const iv = chunk.subarray(0, IV_BYTES);
  const body = chunk.subarray(IV_BYTES);
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: asBufferSource(iv), additionalData },
    key,
    asBufferSource(body),
  );
  return new Uint8Array(plain);
}

// Total bytes that will land in S3 for a given plaintext size and chunk
// size. Each crypto chunk adds `CRYPTO_OVERHEAD_PER_CHUNK` bytes. Used by
// the sender to declare the S3 object size to the backend at add-file
// time, and by the recipient's SW to know the ciphertext byte budget.
//
// A zero-byte plaintext still produces one auth'd empty chunk (IV + tag),
// so the floor is OVERHEAD, not zero. The backend rejects 0-byte files
// earlier on, but keeping this consistent with the upload pipeline avoids
// declaring a size the uploader cannot actually produce.
export function ciphertextSize(
  plaintextSize: number,
  chunkSize: number,
): number {
  if (plaintextSize < 0) return 0;
  if (plaintextSize === 0) return CRYPTO_OVERHEAD_PER_CHUNK;
  const chunks = Math.ceil(plaintextSize / chunkSize);
  return plaintextSize + chunks * CRYPTO_OVERHEAD_PER_CHUNK;
}

export function base64UrlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function base64UrlDecode(s: string): Uint8Array {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
