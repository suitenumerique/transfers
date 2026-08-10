# Transfer encryption — developer guide

This is the consolidated developer reference for encrypted transfers.
The inline comments in the code are the source of truth for individual
mechanisms; this doc gives the map and the rationale, then points back
to the code.

**Every transfer is encrypted client-side.** A per-transfer
``confidential`` flag decides whether the backend also holds the
decryption key (normal) or never sees it (confidential); the crypto is
identical in both.

Audience: developers maintaining the upload pipeline, the download view,
the recipient Service Worker, or the backend serializers that touch the
encryption fields. If you're hunting a bug, start here, then jump to the
file referenced for the mechanism you care about.

## Table of contents

1. [What encryption means here](#what-encryption-means-here)
2. [Threat model](#threat-model)
3. [The crypto primitive](#the-crypto-primitive)
4. [The two chunking levels](#the-two-chunking-levels)
5. [What's ours vs what WebCrypto handles](#whats-ours-vs-what-webcrypto-handles)
6. [Key lifecycle](#key-lifecycle)
7. [Upload pipeline](#upload-pipeline)
8. [What lands in S3](#what-lands-in-s3)
9. [Download pipeline](#download-pipeline)
10. [Authentication binding (AES-GCM + AAD)](#authentication-binding-aes-gcm--aad)
11. [Backend bookkeeping](#backend-bookkeeping)
12. [Normal vs confidential (and Drive)](#normal-vs-confidential-and-drive)
13. [Validation gates and where they live](#validation-gates-and-where-they-live)
14. [Operational notes](#operational-notes)
15. [Failure modes](#failure-modes)

---

## What encryption means here

Files are AES-256-GCM encrypted in the sender's browser before any byte
leaves the page; S3 stores ciphertext only. What varies is who holds the
key, set by the ``confidential`` toggle in the form's options column
(`TransferForm`):

- **Normal (not confidential)**: the browser posts the key to the backend
  at finalize. We store it on the `Transfer` row and serve it to
  recipients via the download API, so they decrypt transparently (a bare
  `/t/<token>` link just works). This is encryption **at rest**: an S3
  breach alone yields nothing (the key lives in the DB), a DB breach
  alone yields nothing (the ciphertext lives in S3). You need both.
- **Confidential**: the key never reaches the backend. In link mode it
  rides in the URL fragment (`#k=…`); in email mode the email carries a
  bare link and the sender passes the key out-of-band, the recipient
  pasting it on the download page. This is true **end-to-end**: only the
  sender's and recipient's browsers ever hold the key.

The choice is made at **finalize**, not locked at draft creation: the
ciphertext is identical either way, so toggling the flag before send
costs nothing (no re-upload, no premature key exposure).

The recipient's browser decrypts on the fly through a Service Worker that
streams plaintext straight to the native download manager, whether the
key came from the backend, the URL fragment, or a paste.

What this is **not**:

- Not transport encryption. TLS already covers the wire; this is about
  what we store and, for confidential transfers, what our infra ever sees.
- Not protection against compromise of our frontend code. A successful
  XSS on the page that runs the encryption sees the key (the JS that
  encrypts has it in memory). LaGaufre is loaded without SRI for
  pragmatic reasons; a compromised widget would break the promise.
- Not anti-replay at the file level. We don't sign upload requests; a
  recipient who shares the link (and, for confidential, the key) gives
  away the full ability to download.

## Threat model

The guarantees differ by mode. **Every** transfer resists an S3-only
breach (ciphertext without the key). **Confidential** transfers
additionally resist a full backend compromise (the key never reaches us).

**In scope (all transfers)**

- Snapshot of the S3 bucket alone (raw ciphertext, no key).
- Tampering at the storage layer: chunk swap, chunk reorder, chunk
  injection. Caught by AES-GCM tag + AAD, see
  [Authentication binding](#authentication-binding-aes-gcm--aad).

**In scope (confidential only)**

- A read-only database snapshot (confidential transfers store no key).
- A compromised Redis broker or Celery worker (no fragment ever reaches
  Celery kwargs, task payloads, or the outbound email body — email
  confidential transfers ship a bare link).
- A full backend compromise short of the frontend: with only ciphertext
  (S3) and no key anywhere, the data stays unreadable.

**Out of scope**

- For **normal** transfers: a breach that reads both S3 **and** the DB.
  The key is a `Transfer` column stored in cleartext (Django DB-level
  encryption would harden this). This is the accepted tradeoff for the
  transparent-download convenience; use confidential for stricter needs.
- Compromise of the sender's browser (key generation site).
- Compromise of the recipient's browser (key decryption/paste site).
- Compromise of our frontend JS (XSS, malicious dependency, supply-chain
  hit on a CDN we trust). We mitigate with CSP (`Caddyfile`), but a
  successful XSS reads the key.
- A social engineer who tricks the sender into copying a confidential link
  with fragment (or the pasted key) somewhere indexed.

## The crypto primitive

**AES-256-GCM via WebCrypto.** Pure browser-native, no library
dependency, hardware-accelerated on modern CPUs (AES-NI / ARMv8 crypto
extensions). Reference: [Galois/Counter Mode][gcm-wiki] covers the full
construction (AES-CTR keystream + GHASH authenticator); [AES][aes-wiki]
is the underlying block cipher.

[gcm-wiki]: https://en.wikipedia.org/wiki/Galois/Counter_Mode
[aes-wiki]: https://en.wikipedia.org/wiki/Advanced_Encryption_Standard

The data is split into fixed-size **crypto chunks**. Each chunk is a
self-contained AEAD blob:

```
[ IV (12 bytes) | ciphertext (N bytes) | GCM tag (16 bytes) ]
```

- **IV**: 96-bit nonce, fresh random per chunk. Prevents keystream
  reuse across chunks (same plaintext + same key + different IV →
  different ciphertext). Transmitted in the clear at the head of the
  chunk; the recipient needs it to decrypt.
- **Ciphertext**: same length as the plaintext of the chunk.
- **Tag**: 128-bit MAC computed by GCM over key + IV + ciphertext +
  AAD. Any modification of any of those inputs makes the tag fail to
  verify; only a key holder can produce a matching tag. WebCrypto's
  `subtle.decrypt` throws on mismatch, so tampering surfaces as a
  download error, never silent corruption.

The constant `CRYPTO_OVERHEAD_PER_CHUNK = 28` (IV + tag) appears
verbatim on both sides (`encryption.ts` and `sw.js`).

## The two chunking levels

"Block" is overloaded. There are two nested scales at play:

| Scale | Size | Chosen by | Visible in JS |
|---|---|---|---|
| **Crypto chunk** (Level 1) | 25 MiB | our `TRANSFER_CHUNK_SIZE` | yes: we slice, encrypt, upload one per S3 part |
| **AES sub-block** (Level 2) | 16 bytes | AES standard (128-bit block cipher) | no: WebCrypto handles it inside `subtle.encrypt` |

A 20 GiB file has ~800 chunks (Level 1), each containing ~1.6 million
sub-blocks (Level 2). One chunk = one S3 multipart part, autonomous:
fresh IV, own tag, no cross-chunk state, so chunks encrypt/upload in
parallel.

Within a chunk, all sub-blocks share the chunk's IV; the AES counter
(last 4 bytes of the 16-byte AES input) increments per sub-block. The
counter is **not stored on S3**: only the 12-byte chunk-level IV is on
the wire; both sides reconstruct the per-sub-block counter from
position.

The rest of this doc uses **chunk** for Level 1 and **sub-block** for
Level 2 when ambiguity matters.

## What's ours vs what WebCrypto handles

The AES-GCM internals (AES, CTR, GHASH, tag calculation, constant-time
comparison, hardware acceleration) live in the browser's native code
behind `crypto.subtle.encrypt` / `crypto.subtle.decrypt`. We only own
the plumbing around those calls.

If a bug looks like it lives in AES-GCM itself, it doesn't; it's in
how we compose the inputs or interpret the outputs.

**Ours** (custom code, `encryption.ts` + `useTransferDraft.ts` + `sw.js`):

- Chunking the file at 25 MiB boundaries via `MultipartUploader`.
- Generating a fresh 12-byte IV per chunk with `crypto.getRandomValues`.
- Building the AAD (`aadForChunk` helper, `fileId:partNumber` UTF-8).
- Wire layout: prepending the IV on encrypt, extracting it on decrypt.
- The two-step download hop (backend `?as=json`, then anonymous S3 fetch).
- Counting `partNumber` on both sides (WebCrypto has no notion of position).
- Persisting `plaintext_size` and `encryption_chunk_size` on the Transfer.
- The server-side mirror of all this in `core/services/encryption.py`,
  used only to encrypt Drive imports at finalize (same layout, same AAD,
  Python `cryptography` instead of WebCrypto).

**API contract** (compact form of what crosses the boundary):

```
crypto.subtle.encrypt(
  { name: "AES-GCM", iv, additionalData },   ← we build these three
  key,                                       ← we hold the CryptoKey
  plaintext,                                 ← we slice this out of the File
)
→ Uint8Array of [ciphertext | tag]           ← we prepend IV before shipping

crypto.subtle.decrypt(
  { name: "AES-GCM", iv, additionalData },   ← iv extracted, aad recomputed
  key,                                       ← reconstructed from URL fragment
  [ciphertext | tag],                        ← payload minus the leading IV
)
→ plaintext, or throws on tag mismatch
```

## Key lifecycle

`generateTransferKey()` (in `encryption.ts`) produces 32 random bytes,
kept in two forms:

- `cryptoKey` (opaque `CryptoKey` handle, `extractable: false`) is
  what `subtle.encrypt`/`decrypt` take. Can't be logged or exported
  back to bytes. Lives only in the sender's page memory.
- `fragment` (43-char base64url string) is the transportable form,
  generated on the first add-file. Where it goes at finalize depends on
  the mode:
  - **Normal**: posted once to `/finalize/` as `encryption_key` and stored
    on the `Transfer`. The download API then serves it to recipients.
  - **Confidential**: never posted. In link mode it stays in the URL
    fragment (`/t/<token>#<fragment>`, which browsers keep client-side);
    in email mode the sender shares it out-of-band.

On the recipient side, `DownloadView` resolves the key from whichever
source applies — the backend (`transfer.encryption_key`, normal), the URL
fragment (confidential link), or a paste box (confidential without a
fragment) — hands it to the SW via `postMessage`, and (for the fragment
case) strips it from the URL bar with `history.replaceState`. The SW
holds the key in memory until the page unmounts (`encryption-unregister`).

## Upload pipeline

```
File (browser RAM or disk-backed File handle)
  │
  │  (page thread, no SW involved)
  ▼
MultipartUploader.slice(chunkSize = TRANSFER_CHUNK_SIZE)
  │
  ▼
For each plaintext chunk at part_number P:
  │
  │   aad = TextEncoder.encode(`${fileId}:${P}`)
  │   iv  = random 12 bytes
  │   ct  = AES-GCM-encrypt(key, plaintext, iv, aad)  ← encryption.encryptChunk
  │   blob = [ iv | ct ]    (tag is at the end of ct)
  │
  ▼
PUT presigned S3 URL with `blob` as the part body
  │
  ▼
After all parts: POST /drafts/{id}/complete-upload/
  └─→ S3 CompleteMultipartUpload + head_object size check
```

Notes:

- Each PUT is browser → S3 direct via a presigned URL. The Django
  worker sees only `add-file`, `sign-part`, `complete-upload`, never
  the key or the plaintext.
- Encrypt runs in the page thread (not a worker); WebCrypto with
  AES-NI does 25 MiB in tens of milliseconds. `MultipartUploader`'s
  parallelism = 4 keeps the network busy without saturating the main
  thread.

## What lands in S3

For plaintext size `P` and chunk size `C` (=
`settings.TRANSFER_CHUNK_SIZE`, 25 MiB default), the S3 object is the
contiguous concatenation of `N = ceil(P / C)` chunks. No padding, no
header, no length prefix.

```
[ IV1 | CT1 | tag1 | IV2 | CT2 | tag2 | ... | IVN | CTN | tagN ]

  12B    C    16B    12B    C    16B          12B   ≤C   16B

Total object size = P + N * 28
```

The last chunk holds the remainder (`P - (N-1) * C` bytes of
plaintext, `≤ C`). Only that one is short; the others are exactly `C`.

**Example** — 60 MiB file with `C = 25 MiB`:

`N = 3` chunks (25 + 25 + 10 MiB of plaintext). Object size =
`60 MiB + 3 * 28 = 60 MiB + 84 bytes`.

Backend storage (see also [Backend bookkeeping](#backend-bookkeeping)):

- `TransferFile.size = P + N * 28` (client-declared, serializer-
  verified against the formula, re-verified by `head_object` at
  complete_upload).
- `TransferFile.plaintext_size = P` (used by the SW as
  `Content-Length` on the decrypted stream).
- `Transfer.encryption_chunk_size = C` (per-transfer, so a later bump
  of the setting doesn't break existing files).

## Download pipeline

The recipient flow is the inverse of upload, with two added wrinkles:
sourcing the key, and the Service Worker that intercepts the byte
stream.

**Phase 1 — page load and SW handshake:**

`DownloadView` first resolves the key from whichever source applies:

- **Normal**: the download payload (`/downloads/<token>/`) carries
  `encryption_key` (the backend holds it). Used directly, transparently.
- **Confidential + link**: the key is in `window.location.hash`; the
  payload's `encryption_key` is empty.
- **Confidential without a fragment** (email, or a bare link): no key
  available, so `DownloadView` shows a paste box (`encryptionState = "need-key"`)
  and waits for the recipient to enter the key.

```
DownloadView mounts and, in order:
    1. resolve key: transfer.encryption_key (normal) OR
       window.location.hash (confidential link) OR paste box
    2. ensureEncryptionServiceWorker():
         register /sw.js if needed, wait for the SW to control the
         page (controllerchange, bounded by CONTROLLER_WAIT_MS)
    3. registerEncryptionKey(sw, token, keyStr, files, chunkSize):
         base64UrlDecode(keyStr) → 32 key bytes
         postMessage to SW { type: "encryption-register", token, ... }
         wait for encryption-register-ack / -error (REGISTER_ACK_WAIT_MS)
    4. for the fragment case, history.replaceState() strips it from
       the URL bar
    5. encryptionState = "ready" → download buttons become clickable
```

**Phase 2 — the user clicks a file:**

```
Page creates <iframe src="/_dl/<token>/<fileId>/<filename>">
    │
    │  (SW fetch handler intercepts this same-origin URL)
    ▼
sw.js handleDownload(token, fileId):
    1. REGISTRY.get(token) → { key, files: Map, apiOrigin }
    2. fetch #1  → backend /api/.../downloads/.../download/?as=json
                   credentialed, records FILE_DOWNLOADED audit event,
                   returns { url: <presigned S3 URL> }, no-store
    3. fetch #2  → presigned S3 URL, anonymous (no cookies)
                   returns a Response whose body is a ReadableStream
                   of ciphertext
    4. pipeThrough(decryptStream(key, chunkSize, plaintextSize, fileId))
    5. returns Response(decryptedStream, headers: {
                    Content-Disposition: attachment; filename=...,
                    Content-Length: plaintextSize,
                    Content-Type: meta.mimeType,
                    Cache-Control: no-store,
                })
    │
    ▼
Browser download manager pulls from the decrypted stream and
writes to disk. No Blob, no RAM, works on 20 GiB files.
```

### Why the SW

The browser's download manager consumes a `Response`. To stream-decrypt
between S3 and the disk without materialising the whole ciphertext in
RAM, something has to sit on the network path. A Service Worker
intercepting `fetch` events is the only browser primitive that can.

We trigger the SW via an iframe rather than an anchor click: anchor
clicks occasionally race SW activation on Firefox (the first click
sometimes bypasses the worker).

### Two-step backend fetch

Following a cross-origin 302 with credentials from a `fetch` is flaky
on Firefox (`NS_ERROR_FAILURE`) and also sends the session cookie to
S3, which we don't want. The `?as=json` branch in `DownloadFileView`
returns the presigned URL in the body instead of redirecting; the SW
fetches that URL anonymously. The audit event still fires on the
first (backend) hop.

### Stream reassembly

The SW receives ciphertext in TCP-paced chunks (~64 KB), not on the
25 MiB crypto boundary. `decryptStream` is a `TransformStream` that
buffers incoming bytes until it has one full ciphertext chunk
(`chunkSize + 28`), decrypts it, enqueues the plaintext, and
increments `partNumber`. `plaintextRemaining` marks when the last
(short) chunk arrives, handled in `flush`. Truncated streams error
out at that check.

## Authentication binding (AES-GCM + AAD)

AES-GCM's tag alone doesn't bind a chunk to a position. An attacker
with **write** access to S3 could swap chunk N of file A with chunk N
of file B (same transfer, same key): both individually verify, but the
recipient ends up with file A's bytes at the wrong offset. Same for
reordering chunks within a file.

The fix is **Additional Authenticated Data**: bytes fed into the tag
computation without being encrypted or transmitted. Both encrypt and
decrypt must produce the same AAD; one bit off and `subtle.decrypt`
throws.

Our AAD is `${fileId}:${partNumber}` UTF-8, recomputed on both sides
(never transmitted). fileId comes from `add-file` on the sender, from
the URL path `/_dl/<token>/<fileId>/...` on the recipient. partNumber
is emitted by `MultipartUploader` and counted by `decryptStream`.

```js
// encryption.ts
export function aadForChunk(fileId, partNumber) {
  return new TextEncoder().encode(`${fileId}:${partNumber}`);
}

// upload (useTransferDraft.ts):
const ct = await encryptChunk(key, buf, aadForChunk(backendId, partNumber));

// download (sw.js):
const aad = encoder.encode(fileId + ":" + partNumber);
const plain = await decryptOne(cryptoKey, ct, aad);
```

Catches: chunk swap across files (different fileId), chunk reorder
within a file (different partNumber). Does not catch: full object
replacement with a fresh encryption under an attacker's key (standard
AES-GCM already blocks that, our key isn't leaked). Replay is a
non-issue because keys aren't reused across transfers.

Verified by `encryption.test.ts::"rejects a chunk whose AAD does not
match the encrypt-side binding"`.

## Backend bookkeeping

```
TransferDraft (lasts from first add-file to finalize / abort):
  encryption_chunk_size    IntegerField, null=True by column, but the
                           viewset sets it unconditionally to
                           settings.TRANSFER_CHUNK_SIZE on create.
                           Server-imposed, never client-provided.

Transfer (created at finalize):
  encryption_chunk_size    IntegerField, null=True, copied from the draft.
                           ``is_encrypted`` == (this IS NOT NULL); NULL
                           marks a plaintext transfer.
  confidential             BooleanField, default False.
  encryption_key           CharField, blank. The base64url key, populated
                           for non-confidential transfers (empty for
                           confidential ones and plaintext ones). Served to
                           recipients by the download API.

TransferFile:
  plaintext_size           IntegerField, the pre-encryption size. Used by
                           the SW as Content-Length and by the UI for
                           display.
  import_failed_at         DateTimeField, null=True. Set when a Drive
                           import fails at finalize (see below).
```

`complete_upload` marks encrypted files `SKIPPED` (ClamAV can't read
ciphertext, and it isn't wired to decrypt).

## Normal vs confidential (and Drive)

The `confidential` flag is chosen at **finalize** and decides the key's
fate. It is orthogonal to `sharing_mode` — both link and email support
either — with one exception: **Drive imports force normal mode**.

| | Normal (not confidential) | Confidential |
|---|---|---|
| Key at finalize | posted as `encryption_key`, stored on `Transfer` | withheld |
| Recipient gets the key from | download API (`encryption_key`) | URL fragment (link) or paste (email / bare link) |
| Link mode | bare `/t/<token>`, transparent decrypt, reusable | `/t/<token>#<fragment>`, shared out-of-band |
| Email mode | bare link in the mail, transparent decrypt | bare link in the mail + key sent separately, recipient pastes |
| Drive import | allowed (encrypted server-side, see below) | rejected at finalize |

**Drive import** is deferred to finalize. During the draft it's only
registered (no fetch); at finalize `import_drive_file_task(file_id,
encryption_key)` fetches the permalink server-to-server and encrypts it
with the transfer key via `core/services/encryption.py` (byte-identical
layout to `encryption.ts`), so a Drive file is indistinguishable from a
browser-encrypted upload. This needs the key, hence normal-mode-only.
Finalize runs a 202 loop (`reason: "drive_importing"`) until every Drive
file lands, then creates the Transfer; a failed import sets
`import_failed_at` and finalize returns `400` `drive_import_failed`.

## Validation gates and where they live

**`DraftAddFileSerializer.validate`** (serializers.py):

| Gate | Triggered by | Status |
|---|---|---|
| `plaintext_size` required | request body | 400, key `plaintext_size` |
| `size` == `_expected_ciphertext_size(plaintext_size, settings.TRANSFER_CHUNK_SIZE)` | request body | 400, key `size` |

**`DraftFinalizeSerializer.validate`** (serializers.py):

| Gate | Triggered by | Status |
|---|---|---|
| `encryption_key` required when `confidential=False` | request body | 400, key `encryption_key` |
| `encryption_key` rejected when `confidential=True` | request body | 400, key `encryption_key` |
| `encryption_key` matches URL-safe base64 | request body | 400, key `encryption_key` |

**`draft.py::finalize`** (viewset):

| Gate | Triggered by | Status |
|---|---|---|
| Drive file present + `confidential=True` | metadata vs draft files | 400, key `confidential` |
| Drive import still running | draft file state | 202, `reason: "drive_importing"` |
| Drive import failed | `import_failed_at` set | 400, `reason: "drive_import_failed"` |

## Operational notes

### Antivirus

ClamAV sees only opaque ciphertext and isn't wired to decrypt, so
`complete_upload` and the Drive import task mark files `SKIPPED`
(`draft.py`), the finalize gate accepts them, and the download view
doesn't re-check (`SKIPPED`, not `PENDING`).

The recipient UI shows a lock icon on **confidential** transfers instead
of a "scanned" badge.

### CSP headers

The Caddyfile pins:
- `script-src 'self' https://static.suite.anct.gouv.fr` (LaGaufre).
- `connect-src` includes the S3 origin (for the SW's anonymous
  fetch) and the two suite domains.
- `frame-ancestors 'none'` (clickjacking).
- `Cross-Origin-Opener-Policy: same-origin-allow-popups` (Drive
  picker needs `window.opener`).
- `Permissions-Policy` locks down sensor/USB/payment/screen-capture.

A successful XSS bypasses encryption entirely. The CSP is what stops an
attacker from chaining a hostile script through a third-party origin.

### Service Worker scope

`/sw.js` is served at the root with `Cache-Control: no-cache` so a new
deploy's SW activates on the next page load. `DownloadView` sends
`encryption-unregister` on unmount so cached keys don't linger across
transfers in the same tab.

### Chunk size knob

`settings.TRANSFER_CHUNK_SIZE` (default 25 MiB) is safe to tune because
each transfer freezes its own chunk size at upload time. Path:

1. `add_file` stamps the current setting onto `TransferDraft.encryption_chunk_size`.
2. `finalize` copies it verbatim to `Transfer.encryption_chunk_size`.
3. On download, `DownloadTransferSerializer` exposes that stored value,
   and the recipient SW peels chunks against it (not against the
   current setting).

Bumping the setting later only affects transfers created after the
bump; existing ones keep decrypting with their historical value. The
recipient never reads `settings.TRANSFER_CHUNK_SIZE` directly.

Tradeoffs when picking the value: smaller chunks give finer streaming
progress but more S3 parts (S3 caps at 10 000); larger chunks use
more RAM per encrypt call (WebCrypto needs the full chunk in RAM
during `subtle.encrypt`).

## Failure modes

| Symptom | Likely cause | Where to look |
|---|---|---|
| Confidential recipient sees the paste box unexpectedly | URL fragment empty or stripped before SW load (link opened without `#…`) | `DownloadView.tsx` `autoKey` resolution + `need-key` state |
| Recipient sees "could not set up decryption helper" | SW didn't take control in time, or `importKey` rejected | `encryptionServiceWorker.ts::ensureEncryptionServiceWorker` (10s timeout) + the `encryption-register-error` path |
| Download truncated / stream errors mid-way | S3 ciphertext truncated, or chunk size doesn't match `Transfer.encryption_chunk_size` | `sw.js::decryptStream::flush` length check |
| Decrypt throws on first chunk | Wrong key (backend served the wrong one, or a bad paste), or AAD mismatch (chunk reordering / corruption) | Inspect `event.error` in the SW's stream; cross-check `transfer.encryption_chunk_size` on the row vs the value the SW received |
| Upload 400 with `size` error | Frontend computed `ciphertextSize` against a different chunk size than the backend's | Check `/config/` carries the same `TRANSFER_CHUNK_SIZE` the backend uses; both sides read from this single source |
| Finalize 400 with `encryption_key` error | Normal transfer posted no key, or a confidential one posted one | `useTransferDraft.ts::submit` finalize body (`confidential` ↔ `encryption_key`) |
| Finalize 400 `drive_import_failed` | The server-side Drive fetch/encrypt failed | `import_drive_file_task`; the row's `import_failed_at` is set — user removes the file and retries |

