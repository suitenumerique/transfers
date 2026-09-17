// Service Worker for decrypted downloads.
//
// The recipient's page extracts the AES-256 key from the URL fragment and
// posts it here, indexed by transfer public_token. When the user clicks a
// download link, the page navigates to a same-origin URL under /_dl/...
// that this worker intercepts: it fetches the ciphertext via the regular
// backend download endpoint (which 302s to S3), streams it through a
// TransformStream that decrypts chunk-by-chunk, and hands the browser back
// a Response with Content-Disposition: attachment — so the native download
// manager streams the plaintext straight to disk, no Blob in RAM.
//
// Chunking matches the sender's `encryption.ts`: each S3 part is one
// self-contained AES-GCM chunk of `[ IV (12B) | ciphertext | tag (16B) ]`,
// where the plaintext slice is `chunkSize` bytes (less for the last chunk).
// Knowing `chunkSize` + `plaintextSize` lets us split the stream
// deterministically without any in-band metadata.

const IV_BYTES = 12;
const TAG_BYTES = 16;
const OVERHEAD = IV_BYTES + TAG_BYTES;
const API_PATH = "/api/v1.0";

// transferToken -> { key: CryptoKey, files: Map<fileId, FileMeta>, apiOrigin: string, expiresAt: number }
// ``apiOrigin`` is the absolute base URL of the Django backend as seen from
// the browser. In prod that's same-origin (Caddy proxies /api/* to the
// backend) and the page sends "" — we fall back to building a relative
// /api/v1.0/... URL. In dev the frontend is on :8980 and the backend on
// :8981, so the page sends the absolute origin and we use it as-is.
//
// In-memory cache in front of IndexedDB. The browser terminates an idle
// worker whenever it likes (Firefox: ~30s, and a backgrounded tab's
// keepalive pings get throttled), which wipes this Map; a download request
// arriving at the fresh instance then reloads the entry from the store.
// The CryptoKey is stored non-extractable, so the raw key bytes never sit
// on disk in readable form. Entries carry the transfer's expiry and are
// dropped past it, and on explicit unregister.
const REGISTRY = new Map();
const DB_NAME = "transferts-decryption";
const DB_VERSION = 1;
const STORE = "entries";

function openStore() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE, { keyPath: "token" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function storeRequest(mode, run) {
  // Small IDB helper: open, run one request in a transaction, resolve with
  // its result once the transaction has committed (a write is only on
  // disk then — the worker can be killed right after). Storage failures
  // are swallowed by callers — the in-memory registry still works for the
  // life of this worker instance.
  return openStore().then(
    (db) =>
      new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, mode);
        const req = run(tx.objectStore(STORE));
        let result;
        req.onsuccess = () => {
          result = req.result;
        };
        req.onerror = () => reject(req.error);
        tx.onabort = () => reject(tx.error);
        tx.oncomplete = () => {
          db.close();
          resolve(result);
        };
      }),
  );
}

// Registrations and releases of one token run one at a time: each is a
// read-modify-write over REGISTRY and the store with awaits in the middle
// (load, live-client lookup), so two pages registering at once, or a
// release racing a fresh registration, must not lose each other's
// clients or delete what the other just wrote.
const TOKEN_QUEUES = new Map();
function serialized(token, work) {
  const previous = TOKEN_QUEUES.get(token) || Promise.resolve();
  const run = previous.then(work, work);
  const settled = run.catch(() => {}).then(() => {
    if (TOKEN_QUEUES.get(token) === settled) TOKEN_QUEUES.delete(token);
  });
  TOKEN_QUEUES.set(token, settled);
  return run;
}

function persistEntry(token, entry) {
  return storeRequest("readwrite", (store) =>
    store.put({
      token,
      key: entry.key,
      files: Array.from(entry.files.entries()),
      apiOrigin: entry.apiOrigin,
      expiresAt: entry.expiresAt,
      clients: Array.from(entry.clients),
    }),
  ).catch(() => {});
}

function forgetEntry(token) {
  return storeRequest("readwrite", (store) => store.delete(token)).catch(() => {});
}

async function loadEntry(token) {
  let row;
  try {
    row = await storeRequest("readonly", (store) => store.get(token));
  } catch {
    return null;
  }
  if (!row) return null;
  if (row.expiresAt && row.expiresAt < Date.now()) {
    void forgetEntry(token);
    return null;
  }
  const entry = {
    key: row.key,
    files: new Map(row.files),
    apiOrigin: row.apiOrigin || "",
    expiresAt: row.expiresAt,
    clients: new Set(row.clients || []),
  };
  REGISTRY.set(token, entry);
  return entry;
}

// Drop the pages that are gone without having released the key (closed
// or navigated away before their unregister went out), so a stale id
// never keeps a key alive on its own.
async function pruneClients(entry) {
  let live;
  try {
    live = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  } catch {
    return;
  }
  const ids = new Set(live.map((c) => c.id));
  for (const id of entry.clients) {
    if (!ids.has(id)) entry.clients.delete(id);
  }
}

// One page letting go of a transfer's key. Other pages of the same
// transfer keep it: the entry only goes once its last client has released
// it (or on expiry), so a download paused in one tab still resumes after
// another tab of the same link was closed.
function releaseEntry(token, clientId) {
  return serialized(token, async () => {
    const entry = REGISTRY.get(token) || (await loadEntry(token));
    if (!entry) return;
    entry.clients.delete(clientId);
    await pruneClients(entry);
    if (entry.clients.size > 0) {
      await persistEntry(token, entry);
      return;
    }
    REGISTRY.delete(token);
    await forgetEntry(token);
  });
}

async function sweepExpired() {
  try {
    const rows = await storeRequest("readonly", (store) => store.getAll());
    const now = Date.now();
    for (const row of rows) {
      if (row.expiresAt && row.expiresAt < now) await forgetEntry(row.token);
    }
  } catch {
    // Storage unavailable — nothing to sweep.
  }
}

self.addEventListener("install", () => {
  // Skip waiting so a fresh SW takes over without a reload — the user's
  // first action after opening the download page is usually clicking
  // "Download", we can't make them refresh first.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Claim existing clients so the very first page load that registered us
  // is already controlled when it postMessages the key.
  event.waitUntil(Promise.all([self.clients.claim(), sweepExpired()]));
});

self.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || typeof data !== "object") return;
  if (data.type === "encryption-register") {
    // Always send back an ack — success or failure — so the page can
    // resolve the in-flight handshake promise either way instead of
    // hanging forever (e.g. malformed key bytes ⇒ importKey rejects).
    event.waitUntil(
      registerKey(data, event.source && event.source.id)
      .then(() => {
        if (event.source && "postMessage" in event.source) {
          event.source.postMessage({
            type: "encryption-register-ack",
            token: data.token,
          });
        }
      })
      .catch((err) => {
        if (event.source && "postMessage" in event.source) {
          event.source.postMessage({
            type: "encryption-register-error",
            token: data.token,
            message: err && err.message ? String(err.message) : "register failed",
          });
        }
      }),
    );
  } else if (data.type === "encryption-unregister") {
    event.waitUntil(releaseEntry(data.token, event.source && event.source.id));
  } else if (data.type === "encryption-ping") {
    // Health-check the page can use to confirm we're alive.
    if (event.source && "postMessage" in event.source) {
      event.source.postMessage({ type: "encryption-pong" });
    }
  }
});

async function registerKey({ token, keyBytes, files, apiOrigin, expiresAt }, clientId) {
  // Throw (don't silently return) on a malformed payload — the message
  // handler routes rejections to `encryption-register-error`, so the page's
  // handshake promise rejects and DownloadView flips to its error
  // state. Silently returning here would let the same handler send
  // back an `encryption-register-ack` even though no entry was recorded.
  if (!token || !(keyBytes instanceof Uint8Array) || !Array.isArray(files)) {
    throw new Error("Malformed encryption-register payload");
  }
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
  return serialized(token, async () => {
    // A page re-registers on every return to the foreground and other tabs
    // of the same link register too: what the earlier registrations
    // accumulated — the pages holding the key, each file's resume
    // capability — carries over.
    const existing = REGISTRY.get(token) || (await loadEntry(token));
    const fileMap = new Map();
    for (const f of files) {
      if (
        !f ||
        typeof f.id !== "string" ||
        !f.id ||
        typeof f.filename !== "string" ||
        !Number.isInteger(f.plaintextSize) ||
        f.plaintextSize <= 0 ||
        !Number.isInteger(f.chunkSize) ||
        f.chunkSize <= 0
      ) {
        // One bad entry drops the whole registration: partial state would let
        // the page ack "ready" and then error only for the unlisted files,
        // which is harder to reason about than a single loud failure.
        throw new Error("Invalid file entry in encryption-register payload");
      }
      const known = existing && existing.files.get(f.id);
      fileMap.set(f.id, {
        plaintextSize: f.plaintextSize,
        chunkSize: f.chunkSize,
        filename: f.filename,
        mimeType: typeof f.mimeType === "string" && f.mimeType
          ? f.mimeType
          : "application/octet-stream",
        resumeToken: (known && known.resumeToken) || "",
      });
    }
    const entry = {
      key,
      files: fileMap,
      clients: new Set(existing ? existing.clients : []),
      apiOrigin: typeof apiOrigin === "string" ? apiOrigin : "",
      // Fallback: a transfer lives at most 30 days, so a payload without an
      // expiry still ages out of the store.
      expiresAt:
        Number.isFinite(expiresAt) && expiresAt > 0
          ? expiresAt
          : Date.now() + 30 * 24 * 3600 * 1000,
    };
    await pruneClients(entry);
    if (clientId) entry.clients.add(clientId);
    REGISTRY.set(token, entry);
    await persistEntry(token, entry);
  });
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const match = url.pathname.match(/^\/_dl\/([^/]+)\/([^/]+)(?:\/.*)?$/);
  if (!match) return;
  const token = match[1];
  const fileId = match[2];
  // Recipient attribution token from the emailed link, forwarded verbatim
  // to the backend's download endpoint. Absent on a bare link.
  const recipientToken = url.searchParams.get("r");
  // Per-click id the page put in the URL; echoed in the notices below so
  // the page matches them to its own pending download and not to another
  // tab's (or an earlier click's) request for the same file.
  const requestId = url.searchParams.get("dl") || "";
  // Wrap in a top-level try/catch: an unhandled throw inside handleDownload
  // makes respondWith() reject, and Firefox reports that as an opaque
  // "ServiceWorker … encountered an unexpected error" with no way to know
  // whether it's a network hiccup, a decrypt failure, or a bug. A readable
  // Response with the message keeps diagnostics possible.
  event.respondWith(
    handleDownload(token, fileId, recipientToken, requestId, event.request)
      .catch((err) => {
        const message =
          (err && err.message) || "Unexpected error while streaming the download.";
        return new Response(message, {
          status: 500,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        });
      })
      .then((response) => {
        // Nothing will stream for an error response: tell the page so it
        // stops showing "preparing…" and drops the iframe. Kept alive by
        // waitUntil so the worker isn't torn down before the message goes.
        if (response.status >= 400) {
          event.waitUntil(
            notifyClients({
              type: "encryption-download-failed",
              requestId,
              fileId,
              status: response.status,
            }),
          );
        }
        return response;
      }),
  );
});

async function handleDownload(token, fileId, recipientToken, requestId, request) {
  const entry = REGISTRY.get(token) || (await loadEntry(token));
  if (!entry) {
    // Neither in memory nor in the store: the page never registered this
    // transfer here, or it unregistered (navigated away) or the entry
    // expired. Message is user-actionable: reopening the link re-registers.
    return new Response("Decryption key not loaded. Reopen the link.", {
      status: 500,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  const meta = entry.files.get(fileId);
  if (!meta) {
    return new Response("Unknown file id.", { status: 404 });
  }

  // Two-step fetch on the SW side:
  //
  //  1. Hit the backend's download endpoint with ``?as=json`` so it returns
  //     ``{"url": "<presigned S3 URL>"}`` instead of a 302. Includes
  //     credentials — the cookie is what authorises the agent's session
  //     and is what records the FILE_DOWNLOADED audit event server-side.
  //  2. Fetch the presigned S3 URL anonymously (no credentials). Doing it
  //     in two hops avoids cross-origin redirect + credentials quirks
  //     (Firefox occasionally NS_ERROR_FAILUREs on those) and keeps the
  //     session cookie from being sent to S3.
  //
  // ``apiOrigin`` is empty in prod (Caddy proxies /api/* same-origin) and
  // absolute in dev (backend on a different port).
  // Every download URL comes with a resume capability for that file
  // (kept with the entry, so it survives a worker restart). It goes back
  // to the backend when this request continues an earlier download — a
  // ranged re-fetch by the download manager, or the page re-sending the
  // file after an interruption (``?resume=1`` on our own URL) — and lets
  // it through on a one-shot transfer whose bytes are still in their
  // post-deactivation grace window.
  const requestedRange = parseRange(
    request && request.headers.get("range"),
    meta.plaintextSize,
  );
  const continuing =
    (requestedRange && requestedRange.start > 0) ||
    (request && new URL(request.url).searchParams.get("resume") === "1");
  const backendUrl =
    (entry.apiOrigin || "") +
    `${API_PATH}/downloads/${token}/files/${fileId}/download/?as=json` +
    (recipientToken ? `&r=${encodeURIComponent(recipientToken)}` : "") +
    (continuing && meta.resumeToken
      ? `&resume=${encodeURIComponent(meta.resumeToken)}`
      : "");
  const meta_resp = await fetch(backendUrl, { credentials: "include" });
  if (!meta_resp.ok) {
    return new Response("Failed to negotiate download URL.", {
      status: meta_resp.status || 502,
    });
  }
  const { url: presignedUrl, resume: resumeToken } = await meta_resp.json();
  if (!presignedUrl) {
    return new Response("Backend returned no download URL.", { status: 502 });
  }
  if (typeof resumeToken === "string" && resumeToken !== meta.resumeToken) {
    // Committed before the stream starts: past respondWith the worker can
    // be killed at any time, and a resume after that needs the token.
    meta.resumeToken = resumeToken;
    await persistEntry(token, entry);
  }
  // A "Range: bytes=START-END" request is served as a 206: chunks are
  // independent AES-GCM blocks, so we fetch S3 from the chunk that holds
  // START, decrypt from that part number, and drop the plaintext before
  // START. Anything unparseable falls back to the full 200 response.
  //
  // The browser's download manager uses this to pause/resume. Chrome
  // routes the resume through the worker and it works. Firefox's download
  // manager never talks to a worker (its pause/resume/retry re-request the
  // URL with the system principal, outside any page), so those land on
  // the static server whatever is advertised here; see
  // docs/ENCRYPTION.md. Resumability needs a validator: the ETag below is
  // stable per file, and a resume whose If-Range names another entity
  // gets the whole file again rather than a mismatched tail.
  const etag = '"' + fileId + "-" + meta.plaintextSize + '"';
  const ifRange = request && request.headers.get("if-range");
  const range =
    ifRange && ifRange !== etag
      ? null
      : parseRange(request && request.headers.get("range"), meta.plaintextSize);
  const startChunk = range ? Math.floor(range.start / meta.chunkSize) : 0;
  const ciphertextOffset = startChunk * (meta.chunkSize + OVERHEAD);
  const upstream = await fetch(presignedUrl, {
    credentials: "omit",
    headers: ciphertextOffset > 0 ? { Range: "bytes=" + ciphertextOffset + "-" } : {},
  });
  if (!upstream.ok || !upstream.body) {
    return new Response("Failed to fetch encrypted bytes.", {
      status: upstream.status || 502,
    });
  }
  if (ciphertextOffset > 0 && upstream.status !== 206) {
    // Storage ignored the range and sent the whole object: we can't line
    // that up with the chunk we asked for, so refuse rather than corrupt.
    return new Response("Storage does not support ranged reads.", { status: 502 });
  }

  let decrypted = upstream.body.pipeThrough(
    decryptStream(
      entry.key,
      meta.chunkSize,
      meta.plaintextSize,
      fileId,
      startChunk + 1,
      requestId,
    ),
  );
  const headers = {
    "Content-Type": meta.mimeType,
    "Content-Disposition":
      "attachment; filename=" + rfc5987FilenameStar(meta.filename),
    "Accept-Ranges": "bytes",
    ETag: etag,
    // Tell the browser not to cache the decrypted stream — and irrelevant
    // anyway because the URL is one-shot per click.
    "Cache-Control": "no-store",
  };
  // The browser cancelling the body (download paused or cancelled from
  // its download manager) is reported to the page: on Firefox the
  // recipient must restart from the page, and this is the only signal
  // the page ever gets of it.
  const onCancel = () =>
    notifyClients({ type: "encryption-download-interrupted", requestId, fileId });
  if (!range) {
    headers["Content-Length"] = String(meta.plaintextSize);
    return new Response(watchCancel(decrypted, onCancel), { headers });
  }
  const skip = range.start - startChunk * meta.chunkSize;
  const length = range.end - range.start + 1;
  decrypted = decrypted.pipeThrough(sliceStream(skip, length));
  headers["Content-Length"] = String(length);
  headers["Content-Range"] =
    "bytes " + range.start + "-" + range.end + "/" + meta.plaintextSize;
  return new Response(watchCancel(decrypted, onCancel), { status: 206, headers });
}

// Pass ``readable`` through unchanged and call ``onCancel`` if the
// consumer cancels it (a pipe forwards the cancel upstream, so the
// decrypt transform and the S3 fetch stop too). A normal end-of-stream
// or an upstream error is not a cancel.
function watchCancel(readable, onCancel) {
  const reader = readable.getReader();
  return new ReadableStream({
    pull(controller) {
      return reader.read().then(({ done, value }) => {
        if (done) controller.close();
        else controller.enqueue(value);
      });
    },
    cancel(reason) {
      onCancel();
      return reader.cancel(reason);
    },
  });
}

// "bytes=START-END" / "bytes=START-" → { start, end } clamped to the file,
// or null for anything else (no header, multiple ranges, suffix ranges).
function parseRange(header, size) {
  if (!header) return null;
  const m = /^bytes=(\d+)-(\d*)$/.exec(header.trim());
  if (!m) return null;
  const start = Number(m[1]);
  const end = m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
  if (!Number.isSafeInteger(start) || start < 0 || start >= size || end < start) return null;
  return { start, end };
}

// Drop the first ``skip`` bytes, then pass through ``length`` bytes and
// close — turns a from-chunk-boundary plaintext stream into the exact
// byte range the browser asked for.
function sliceStream(skip, length) {
  let toSkip = skip;
  let remaining = length;
  return new TransformStream({
    transform(chunk, controller) {
      let piece = chunk;
      if (toSkip > 0) {
        const drop = Math.min(toSkip, piece.length);
        toSkip -= drop;
        piece = piece.subarray(drop);
      }
      if (remaining <= 0 || piece.length === 0) return;
      if (piece.length > remaining) piece = piece.subarray(0, remaining);
      remaining -= piece.length;
      controller.enqueue(piece);
      // Range served in full: close our side and error the writable one,
      // which cancels the decrypt transform and the S3 fetch behind it
      // instead of decrypting the rest of the file into the void.
      if (remaining <= 0) controller.terminate();
    },
  });
}

function decryptStream(
  cryptoKey,
  chunkSize,
  plaintextSize,
  fileId,
  startPart = 1,
  requestId = "",
) {
  // Per-chunk ciphertext size on S3. The last chunk is shorter; we figure
  // out which one we're on by tracking how many plaintext bytes remain.
  // Each chunk's AAD is `${fileId}:${partNumber}:${parts}` and must match
  // what the uploader bound the GCM tag to — see encryption.aadForChunk.
  // ``parts`` is computed locally from chunkSize + plaintextSize (same
  // formula as ``totalParts`` on the frontend and ``total_parts`` in the
  // backend) so no extra metadata has to travel through the download URL.
  const ciphertextChunkSize = chunkSize + OVERHEAD;
  const encoder = new TextEncoder();
  const parts = plaintextSize <= 0 ? 1 : Math.ceil(plaintextSize / chunkSize);
  // Network chunks are queued as-is and only joined once a whole ciphertext
  // chunk is in: joining on every arrival would copy the growing buffer
  // each time (Firefox delivers fetch bodies in ~32 KiB pieces, i.e.
  // hundreds of copies of up to 25 MiB per chunk).
  const queue = [];
  let queued = 0;
  // ``parts`` (in the AAD) is always the file's total; a ranged read just
  // starts the count at ``startPart`` with the plaintext still ahead of it.
  let plaintextRemaining = plaintextSize - (startPart - 1) * chunkSize;
  let partNumber = startPart;
  let streaming = false;

  const takeAll = () => {
    const out = new Uint8Array(queued);
    let offset = 0;
    for (const piece of queue) {
      out.set(piece, offset);
      offset += piece.length;
    }
    queue.length = 0;
    queued = 0;
    return out;
  };
  const enqueuePlain = (controller, plain) => {
    controller.enqueue(plain);
    if (!streaming) {
      streaming = true;
      notifyClients({ type: "encryption-download-streaming", requestId, fileId });
    }
  };

  return new TransformStream({
    transform: async (chunk, controller) => {
      // We can't decrypt until we have a full ciphertext chunk (or hit the
      // file's end), since AES-GCM needs the tag to authenticate.
      const piece = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk);
      queue.push(piece);
      queued += piece.length;

      // While we still have full non-final chunks queued, decrypt them.
      while (plaintextRemaining > chunkSize && queued >= ciphertextChunkSize) {
        const buffered = takeAll();
        const ct = buffered.subarray(0, ciphertextChunkSize);
        const rest = buffered.subarray(ciphertextChunkSize);
        if (rest.length > 0) {
          queue.push(rest);
          queued = rest.length;
        }
        const aad = encoder.encode(fileId + ":" + partNumber + ":" + parts);
        const plain = await decryptOne(cryptoKey, ct, aad);
        enqueuePlain(controller, plain);
        plaintextRemaining -= plain.length;
        partNumber += 1;
      }
    },
    flush: async (controller) => {
      // Last chunk: whatever's left should be exactly
      // `plaintextRemaining + OVERHEAD` bytes. If not, the upstream stream
      // was truncated — propagate the failure so the browser surfaces a
      // partial download as an error. Zero-byte plaintext is not a special
      // case: the sender still emits one chunk (just IV + tag, OVERHEAD
      // bytes) so the recipient authenticates it too, discards the empty
      // plaintext, and catches a swapped-in nonsense trailing chunk.
      const pending = takeAll();
      const expected = plaintextRemaining + OVERHEAD;
      if (pending.length !== expected) {
        controller.error(
          new Error(
            "Truncated ciphertext stream (expected " +
              expected +
              " trailing bytes, got " +
              pending.length +
              ")",
          ),
        );
        return;
      }
      const aad = encoder.encode(fileId + ":" + partNumber + ":" + parts);
      const plain = await decryptOne(cryptoKey, pending, aad);
      if (plain.length > 0) enqueuePlain(controller, plain);
      plaintextRemaining -= plain.length;
      if (plaintextRemaining !== 0) {
        controller.error(
          new Error(
            "Plaintext size mismatch after decryption (residual " +
              plaintextRemaining +
              ")",
          ),
        );
      }
    },
  });
}

async function decryptOne(key, ciphertextChunk, additionalData) {
  const iv = ciphertextChunk.subarray(0, IV_BYTES);
  const body = ciphertextChunk.subarray(IV_BYTES);
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv, additionalData },
    key,
    body,
  );
  return new Uint8Array(plain);
}

// Tell every open page of this origin something about a download in
// flight: its first decrypted bytes going out (that is when the browser's
// download UI appears — Firefox only shows it once body bytes arrive,
// Chrome on headers — so the page can stop showing "preparing…"), an
// error answered instead of a stream, or the browser cancelling the
// stream midway.
function notifyClients(message) {
  return self.clients
    .matchAll({ type: "window", includeUncontrolled: true })
    .then((clients) => {
      for (const client of clients) client.postMessage(message);
    })
    .catch(() => {});
}

// RFC 5987 filename* with UTF-8 encoding so non-ASCII names survive
// Content-Disposition. We also include an ASCII fallback for ancient
// clients via a sanitised plain filename — but modern browsers all pick
// filename* when present.
function rfc5987FilenameStar(name) {
  const ascii = name.replace(/[^\x20-\x7e]+/g, "_").replace(/["\\]/g, "_");
  const utf8 = encodeURIComponent(name);
  return '"' + ascii + "\"; filename*=UTF-8''" + utf8;
}
