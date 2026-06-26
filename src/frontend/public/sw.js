// Service Worker for E2E-decrypted downloads.
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
// Chunking matches the sender's `e2eCrypto.ts`: each S3 part is one
// self-contained AES-GCM chunk of `[ IV (12B) | ciphertext | tag (16B) ]`,
// where the plaintext slice is `chunkSize` bytes (less for the last chunk).
// Knowing `chunkSize` + `plaintextSize` lets us split the stream
// deterministically without any in-band metadata.

const IV_BYTES = 12;
const TAG_BYTES = 16;
const OVERHEAD = IV_BYTES + TAG_BYTES;
const API_PATH = "/api/v1.0";

// transferToken -> { key: CryptoKey, files: Map<fileId, FileMeta>, apiOrigin: string }
// ``apiOrigin`` is the absolute base URL of the Django backend as seen from
// the browser. In prod that's same-origin (Caddy proxies /api/* to the
// backend) and the page sends "" — we fall back to building a relative
// /api/v1.0/... URL. In dev the frontend is on :8980 and the backend on
// :8981, so the page sends the absolute origin and we use it as-is.
const REGISTRY = new Map();

self.addEventListener("install", () => {
  // Skip waiting so a fresh SW takes over without a reload — the user's
  // first action after opening the download page is usually clicking
  // "Download", we can't make them refresh first.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Claim existing clients so the very first page load that registered us
  // is already controlled when it postMessages the key.
  event.waitUntil(self.clients.claim());
});

self.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || typeof data !== "object") return;
  if (data.type === "e2e-register") {
    void registerKey(data).then(() => {
      // Acknowledge so the page knows it's safe to enable the download
      // button (the SW is now ready to intercept).
      if (event.source && "postMessage" in event.source) {
        event.source.postMessage({ type: "e2e-register-ack", token: data.token });
      }
    });
  } else if (data.type === "e2e-unregister") {
    REGISTRY.delete(data.token);
  } else if (data.type === "e2e-ping") {
    // Health-check the page can use to confirm we're alive.
    if (event.source && "postMessage" in event.source) {
      event.source.postMessage({ type: "e2e-pong" });
    }
  }
});

async function registerKey({ token, keyBytes, files, apiOrigin }) {
  if (!token || !(keyBytes instanceof Uint8Array) || !Array.isArray(files)) return;
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
  const fileMap = new Map();
  for (const f of files) {
    fileMap.set(f.id, {
      plaintextSize: f.plaintextSize,
      chunkSize: f.chunkSize,
      filename: f.filename,
      mimeType: f.mimeType || "application/octet-stream",
    });
  }
  REGISTRY.set(token, {
    key,
    files: fileMap,
    apiOrigin: typeof apiOrigin === "string" ? apiOrigin : "",
  });
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const match = url.pathname.match(/^\/_dl\/([^/]+)\/([^/]+)(?:\/.*)?$/);
  if (!match) return;
  const token = match[1];
  const fileId = match[2];
  event.respondWith(handleDownload(token, fileId));
});

async function handleDownload(token, fileId) {
  const entry = REGISTRY.get(token);
  if (!entry) {
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
  const backendUrl =
    (entry.apiOrigin || "") +
    `${API_PATH}/downloads/${token}/files/${fileId}/download/?as=json`;
  const meta_resp = await fetch(backendUrl, { credentials: "include" });
  if (!meta_resp.ok) {
    return new Response("Failed to negotiate download URL.", {
      status: meta_resp.status || 502,
    });
  }
  const { url: presignedUrl } = await meta_resp.json();
  if (!presignedUrl) {
    return new Response("Backend returned no download URL.", { status: 502 });
  }
  const upstream = await fetch(presignedUrl, { credentials: "omit" });
  if (!upstream.ok || !upstream.body) {
    return new Response("Failed to fetch encrypted bytes.", {
      status: upstream.status || 502,
    });
  }

  const decrypted = upstream.body.pipeThrough(
    decryptStream(entry.key, meta.chunkSize, meta.plaintextSize),
  );

  return new Response(decrypted, {
    headers: {
      "Content-Type": meta.mimeType,
      "Content-Length": String(meta.plaintextSize),
      "Content-Disposition":
        "attachment; filename=" + rfc5987FilenameStar(meta.filename),
      // Tell the browser not to cache the decrypted stream — and irrelevant
      // anyway because the URL is one-shot per click.
      "Cache-Control": "no-store",
    },
  });
}

function decryptStream(cryptoKey, chunkSize, plaintextSize) {
  // Per-chunk ciphertext size on S3. The last chunk is shorter; we figure
  // out which one we're on by tracking how many plaintext bytes remain.
  const ciphertextChunkSize = chunkSize + OVERHEAD;
  let pending = new Uint8Array(0);
  let plaintextRemaining = plaintextSize;

  return new TransformStream({
    transform: async (chunk, controller) => {
      // Append the freshly-arrived bytes to whatever was left over from the
      // last transform call. We can't decrypt until we have a full
      // ciphertext chunk (or hit the file's end), since AES-GCM needs the
      // tag to authenticate.
      pending = concat(pending, chunk);

      // While we still have full non-final chunks queued, decrypt them.
      while (
        plaintextRemaining > chunkSize &&
        pending.length >= ciphertextChunkSize
      ) {
        const ct = pending.subarray(0, ciphertextChunkSize);
        pending = pending.slice(ciphertextChunkSize);
        const plain = await decryptOne(cryptoKey, ct);
        controller.enqueue(plain);
        plaintextRemaining -= plain.length;
      }
    },
    flush: async (controller) => {
      // Last chunk: whatever's left in `pending` should be exactly
      // `plaintextRemaining + OVERHEAD` bytes. If not, the upstream stream
      // was truncated — propagate the failure so the browser surfaces a
      // partial download as an error.
      if (plaintextRemaining > 0) {
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
        const plain = await decryptOne(cryptoKey, pending);
        controller.enqueue(plain);
        plaintextRemaining -= plain.length;
      }
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

async function decryptOne(key, ciphertextChunk) {
  const iv = ciphertextChunk.subarray(0, IV_BYTES);
  const body = ciphertextChunk.subarray(IV_BYTES);
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv },
    key,
    body,
  );
  return new Uint8Array(plain);
}

function concat(a, b) {
  if (a.length === 0) return b instanceof Uint8Array ? b : new Uint8Array(b);
  const bArr = b instanceof Uint8Array ? b : new Uint8Array(b);
  const out = new Uint8Array(a.length + bArr.length);
  out.set(a, 0);
  out.set(bArr, a.length);
  return out;
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
