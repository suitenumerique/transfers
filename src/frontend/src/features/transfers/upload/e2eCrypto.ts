// Client-side AES-256-GCM helpers for end-to-end encrypted transfers.
//
// Threat model: the key is generated here, embedded in the download URL
// fragment (`#k=...`), and never leaves the browser of the sender (until
// the recipient opens the link). The backend stores ciphertext only and
// has no way to read the files.
//
// Layout per crypto chunk on S3:
//
//     [ IV (12 bytes) | ciphertext (N bytes) | GCM tag (16 bytes) ]
//
// One crypto chunk maps to one S3 multipart part. The plaintext chunk size
// is fixed for the whole transfer (`PLAINTEXT_CHUNK_SIZE`) so the recipient
// can compute part boundaries from the file's plaintext size without any
// out-of-band metadata. The last chunk is shorter — same layout, just less
// plaintext.
//
// IVs are random per chunk: with a 256-bit key the birthday probability of
// an IV collision matters only at ~2^48 chunks, which is unreachable inside
// our 20 GiB / 25 MiB ≈ 800-chunks-per-file budget.

export const CRYPTO_OVERHEAD_PER_CHUNK = 12 /* IV */ + 16 /* GCM tag */;

// Chunk size in plaintext bytes. Aligned with the backend's
// TRANSFER_CHUNK_SIZE default so one crypto chunk = one S3 part. Kept here
// (and persisted on the Transfer) so changing the backend default later
// doesn't break decryption of existing files.
export const PLAINTEXT_CHUNK_SIZE = 25 * 1024 * 1024;

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

export async function encryptChunk(
  key: CryptoKey,
  plaintext: BufferSource,
): Promise<Uint8Array> {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const ct = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: asBufferSource(iv) },
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
): Promise<Uint8Array> {
  if (chunk.length < IV_BYTES + 16) {
    throw new Error("Ciphertext chunk too short");
  }
  const iv = chunk.subarray(0, IV_BYTES);
  const body = chunk.subarray(IV_BYTES);
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: asBufferSource(iv) },
    key,
    asBufferSource(body),
  );
  return new Uint8Array(plain);
}

// Total bytes that will land in S3 for a given plaintext size and chunk
// size. Each crypto chunk adds `CRYPTO_OVERHEAD_PER_CHUNK` bytes. Used by
// the sender to declare the S3 object size to the backend at add-file
// time, and by the recipient's SW to know the ciphertext byte budget.
export function ciphertextSize(
  plaintextSize: number,
  chunkSize: number,
): number {
  if (plaintextSize <= 0) return 0;
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
