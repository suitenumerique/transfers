# End-to-end encryption — developer guide

This is the consolidated developer reference for E2E-encrypted transfers.
The inline comments in the code are the source of truth for individual
mechanisms; this doc gives the map and the rationale, then points back
to the code.

Audience: developers maintaining the upload pipeline, the download view,
the recipient Service Worker, or the backend serializers that touch the
E2E fields. If you're hunting a bug, start here, then jump to the file
referenced for the mechanism you care about.

## Table of contents

1. [What "E2E" means here](#what-e2e-means-here)
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
12. [Modes: link vs email](#modes-link-vs-email)
13. [Validation gates and where they live](#validation-gates-and-where-they-live)
14. [Operational notes](#operational-notes)
15. [Failure modes](#failure-modes)

---

## What "E2E" means here

End-to-end encryption is **opt-in per transfer**, toggled by the sender
above the dropzone (`TransferForm`). When the flag is on:

- The browser generates a fresh AES-256 key. The backend never sees it
  in link mode; in email mode the key transits the SMTP pipeline once
  before being forgotten (documented trade-off, see
  [Modes](#modes-link-vs-email)).
- Every byte of every file is encrypted in the sender's browser before
  it leaves the page.
- S3 stores ciphertext only. The backend has no path to read the bytes.
- The recipient's browser, with the key extracted from the URL fragment,
  decrypts on the fly through a Service Worker that streams plaintext
  straight to the native download manager.

What this is **not**:

- Not transport encryption. TLS already covers the wire; E2E is about
  what we store and what our infra ever sees.
- Not protection against compromise of our frontend code. A successful
  XSS on the page that runs the encryption sees the key (the JS that
  encrypts has it in memory). LaGaufre is loaded without SRI for
  pragmatic reasons; a compromised widget would break the E2E promise.
- Not anti-replay at the file level. We don't sign upload requests; a
  recipient who shares the link gives away the full ability to download.

## Threat model

**In scope**

- Snapshot of the S3 bucket (an attacker who steals the raw ciphertext
  bytes cannot read them).
- A read-only database snapshot (transfers store no keys).
- A compromised Redis broker or Celery worker (only sees ciphertext
  references; in email mode sees the key transiently for the seconds
  the send task runs).
- Tampering at the storage layer: chunk swap, chunk reorder, chunk
  injection. Caught by AES-GCM tag + AAD, see
  [Authentication binding](#authentication-binding-aes-gcm--aad).

**Out of scope**

- Compromise of the sender's browser (key generation site).
- Compromise of the recipient's browser (key decryption site).
- Compromise of our frontend JS (XSS, malicious dependency, supply-chain
  hit on a CDN we trust). We mitigate with CSP (`Caddyfile`), but a
  successful XSS reads the key.
- Mail providers / mailbox owners in email mode (the key is literally
  in the email body).
- A social engineer who tricks the sender into copying the link with
  fragment somewhere indexed (chat history, ticket system).

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
verbatim on both sides (`e2eCrypto.ts` and `sw.js`).

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

**Ours** (custom code, `e2eCrypto.ts` + `useTransferDraft.ts` + `sw.js`):

- Chunking the file at 25 MiB boundaries via `MultipartUploader`.
- Generating a fresh 12-byte IV per chunk with `crypto.getRandomValues`.
- Building the AAD (`aadForChunk` helper, `fileId:partNumber` UTF-8).
- Wire layout: prepending the IV on encrypt, extracting it on decrypt.
- The two-step download hop (backend `?as=json`, then anonymous S3 fetch).
- Counting `partNumber` on both sides (WebCrypto has no notion of position).
- Persisting `plaintext_size` and `encryption_chunk_size` on the Transfer.

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

`generateTransferKey()` (in `e2eCrypto.ts`) produces 32 random bytes,
kept in two forms:

- `cryptoKey` (opaque `CryptoKey` handle, `extractable: false`) is
  what `subtle.encrypt`/`decrypt` take. Can't be logged or exported
  back to bytes. Lives only in the sender's page memory.
- `fragment` (43-char base64url string) is the transportable form.
  Embedded in `/t/<token>#<fragment>`; the URL fragment is never sent
  in HTTP requests (browsers keep it client-side), so it stays out of
  our backend in link mode. In email mode it's additionally posted to
  `/finalize/` and forwarded as a Celery kwarg to the email task.

On the recipient side, `DownloadView` reads the fragment on mount,
hands it to the SW via `postMessage`, then strips it from the URL bar
with `history.replaceState`. The SW holds the key in memory until the
page unmounts (`e2e-unregister`).

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
  │   ct  = AES-GCM-encrypt(key, plaintext, iv, aad)  ← e2eCrypto.encryptChunk
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
the key extraction from the URL fragment, and the Service Worker that
intercepts the actual byte stream.

**Phase 1 — page load and SW handshake:**

```
Recipient opens https://transferts.../t/<token>#<fragment>
    │
    ▼
DownloadView mounts and, in order:
    1. reads window.location.hash → fragment
    2. calls ensureE2eServiceWorker():
         registers /sw.js if not already, then waits for the SW to
         take control of the page (controllerchange event, bounded
         by CONTROLLER_WAIT_MS)
    3. calls registerE2eKey(sw, token, fragment, files, chunkSize):
         base64UrlDecode(fragment) → 32 key bytes
         postMessage to SW { type: "e2e-register", token, ... }
         waits for e2e-register-ack (or -error), bounded by
         REGISTER_ACK_WAIT_MS
    4. history.replaceState() strips #<fragment> from the URL bar
    5. sets e2eState = "ready" → download buttons become clickable
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
// e2eCrypto.ts
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

Verified by `e2eCrypto.test.ts::"rejects a chunk whose AAD does not
match the encrypt-side binding"`.

## Backend bookkeeping

Three fields, two model rows:

```
TransferDraft (lasts from first add-file to finalize / abort):
  e2e_encrypted            BooleanField, default False
  encryption_chunk_size    IntegerField, null=True
                           Set to settings.TRANSFER_CHUNK_SIZE by the
                           viewset on create when e2e_encrypted=True.
                           Server-imposed, never client-provided.

Transfer (created at finalize, mirrors the above):
  e2e_encrypted            BooleanField, default False
  encryption_chunk_size    IntegerField, null=True
                           Copied verbatim from the draft at finalize.

TransferFile:
  plaintext_size           IntegerField, null=True
                           Set only when the parent (draft / transfer)
                           is E2E. Used by the SW as Content-Length
                           and by the recipient UI for size display.
```

The draft mirrors the Transfer fields so `complete_upload` can decide
"skip the antivirus scan" before finalize runs (an E2E draft's files
are SKIPPED at completion; see the scan section in `draft.py`).

## Modes: link vs email

| Aspect | Link mode | Email mode |
|---|---|---|
| `sharing_mode` value | `link` | `email` |
| Key transport | URL fragment, sender shares manually | URL fragment embedded in an email the backend sends |
| Backend ever sees the key | **No** | **Yes**, transiently |
| Key path on the wire | sender browser → URL fragment → recipient browser | sender browser → HTTPS to /finalize/ → Redis (Celery broker) → Celery worker → SMTP relay → MTA hops → recipient mailbox |
| Persistence on our infra | None | None (key is a task kwarg, not a DB column) |

**Link mode is the air-gapped path**: the only system that ever holds
the key is the sender's browser, the recipient's browser, and whatever
the sender uses to share the link (Signal, Matrix, in-person, etc.).

**Email mode is convenient but degraded**: the key sits in:
- The HTTPS request body to `/drafts/<id>/finalize/` (terminated at
  Caddy, so plaintext in our process memory briefly).
- Redis (Celery broker) until the `send_recipient_invitations_task`
  picks it up.
- The Celery worker's process memory during email rendering.
- The SMTP relay's queue (Mailjet, SES, etc.).
- Every MTA hop (opportunistic STARTTLS, may degrade to plaintext on
  unconfigured relays).
- The recipient's mailbox (plaintext, indefinitely).

The frontend warns the user explicitly when they toggle E2E in email
mode (the Alert in `TransferForm`).

**Validation** (`DraftFinalizeSerializer.validate` + `draft.py:finalize`):
- `key_fragment` only accepted when `sharing_mode == "email"`. Posting
  it in link mode is a 400.
- `key_fragment` required when E2E + email. Posting an empty fragment
  on an E2E email transfer is a 400 (otherwise we'd send a broken link).
- `key_fragment` rejected when non-E2E + email (extra field on a
  transfer that doesn't need it).
- Field-level: `key_fragment` is URL-safe base64 only (validated by
  `_KEY_FRAGMENT_RE` in `serializers.py`).

The key never reaches the database. It rides as a kwarg to
`send_recipient_invitations_task.delay(transfer_id, key_fragment=...)`
and lives only as long as Redis holds the task payload and the worker
holds the in-memory string.

## Validation gates and where they live

The serializer enforces input-shape rules; the viewset enforces
state-dependent rules (anything involving `draft.e2e_encrypted` or
`draft.encryption_chunk_size`). The split keeps the serializer
testable in isolation.

**`DraftAddFileSerializer.validate`** (serializers.py):

| Gate | Triggered by | Status |
|---|---|---|
| `plaintext_size` required when `e2e_encrypted=True` | request body | 400, key `plaintext_size` |
| `source_url` rejected when `e2e_encrypted=True` | request body | 400, key `source_url` |
| `size` matches `_e2e_expected_ciphertext_size(plaintext_size, settings.TRANSFER_CHUNK_SIZE)` | request body | 400, key `size` |
| `plaintext_size` rejected when `e2e_encrypted=False` | request body | 400, key `plaintext_size` |

**`DraftFinalizeSerializer.validate`**:

| Gate | Triggered by | Status |
|---|---|---|
| `key_fragment` only in email mode | request body | 400, key `key_fragment` |
| `key_fragment` matches URL-safe base64 alphabet | request body | 400, key `key_fragment` |

**`draft.py::add_file`** (viewset, follow-up to existing draft):

| Gate | Triggered by | Status |
|---|---|---|
| `e2e_encrypted` flag matches the draft's mode | request body vs draft row | 400, key `e2e_encrypted` |
| No `source_url` on E2E draft | request body vs draft row | 400, key `source_url` (defense in depth behind the mode-match check) |

**`draft.py::finalize`** (viewset, E2E + email cross-check):

| Gate | Triggered by | Status |
|---|---|---|
| `key_fragment` required when finalizing E2E in email mode | metadata vs draft.e2e_encrypted | 400, key `key_fragment` |
| `key_fragment` rejected when finalizing non-E2E in email mode | metadata vs draft.e2e_encrypted | 400, key `key_fragment` |

## Operational notes

### Antivirus

E2E ciphertext is opaque random bytes; ClamAV sees nothing useful and
would burn CPU for no signal. `complete_upload` marks E2E files as
`SKIPPED` directly (`draft.py`), the finalize gate accepts them, the
download view doesn't check (already `SKIPPED`, not `PENDING`).

The recipient UI does NOT show a "scanned" badge for E2E files; it
shows the E2E lock icon instead.

### CSP headers

The Caddyfile pins:
- `script-src 'self' https://static.suite.anct.gouv.fr` (LaGaufre).
- `connect-src` includes the S3 origin (for the SW's anonymous
  fetch) and the two suite domains.
- `frame-ancestors 'none'` (clickjacking).
- `Cross-Origin-Opener-Policy: same-origin-allow-popups` (Drive
  picker needs `window.opener`).
- `Permissions-Policy` locks down sensor/USB/payment/screen-capture.

A successful XSS bypasses E2E entirely. The CSP is what stops an
attacker from chaining a hostile script through a third-party origin.

### Service Worker scope

`/sw.js` is served at the root with `Cache-Control: no-cache` so a new
deploy's SW activates on the next page load. `DownloadView` sends
`e2e-unregister` on unmount so cached keys don't linger across
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
| Recipient sees "decryption key missing" | URL fragment empty or stripped before SW load | `DownloadView.tsx` lazy initial state |
| Recipient sees "could not set up decryption helper" | SW didn't take control in time, or `importKey` rejected | `e2eServiceWorker.ts::ensureE2eServiceWorker` (10s timeout) + the `e2e-register-error` path |
| Download truncated / stream errors mid-way | S3 ciphertext truncated, or chunk size doesn't match `Transfer.encryption_chunk_size` | `sw.js::decryptStream::flush` length check |
| Decrypt throws on first chunk | Wrong key (fragment doesn't match), or AAD mismatch (chunk reordering / corruption) | Inspect `event.error` in the SW's stream; cross-check `transfer.encryption_chunk_size` on the row vs the value the SW received |
| Upload 400 with `size` error | Frontend computed `ciphertextSize` against a different chunk size than the backend's | Check `/config/` carries the same `TRANSFER_CHUNK_SIZE` the backend uses; both sides read from this single source |
| Upload 400 with `plaintext_size` error | Sender forgot to declare it, or declared it on a non-E2E transfer | `useTransferDraft.ts::registerFile` |
| Finalize 400 with `key_fragment` error | E2E + email but the page didn't accumulate the fragment, or link mode tried to ship it | `useTransferDraft.ts::submit` finalize body |

