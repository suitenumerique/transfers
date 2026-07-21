// Helpers for the recipient side of encryption: register the decryption SW and
// hand it the per-file metadata + the AES key extracted from the URL
// fragment. The SW lives at /sw.js (scope /) and intercepts /_dl/...
// requests to stream-decrypt the ciphertext into the native download
// manager.

import type { DownloadTransferFile } from "@/features/api/types";
import { base64UrlDecode } from "./encryption";

export interface ServiceWorkerFilePayload {
  id: string;
  plaintextSize: number;
  chunkSize: number;
  filename: string;
  mimeType: string;
}

// Bound the controllerchange wait. On the first-ever registration the
// browser normally claims within tens of ms after ``navigator.serviceWorker
// .ready`` resolves, so 2s is comfortable headroom. On a hard-reload the
// event never fires — no point stalling further before the auto-reload
// kicks in. If the wait times out and no controller lands, the hard-reload
// recovery branch below handles it (reload once; second attempt falls
// through to the visible error if the SW is genuinely broken).
const CONTROLLER_WAIT_MS = 2_000;
// Bound the postMessage handshake the same way. importKey on the SW side
// usually completes in tens of milliseconds; if we don't see an ack inside
// 5s, something is broken (worker terminated, message lost, etc.).
const REGISTER_ACK_WAIT_MS = 5_000;
// Session flag: a hard-reload (Ctrl+Shift+R / Cmd+Shift+R) deliberately
// bypasses the SW for that navigation — the SW is still *registered*, just
// not *controlling* the page, and no ``controllerchange`` will ever fire
// on this load. When we detect that shape (active registration, null
// controller), we reload once so the follow-up navigation goes through
// the SW normally. The sessionStorage flag makes the reload single-shot:
// if the second attempt still has no controller, the SW is genuinely
// broken and we fall through to the visible error.
const HARD_RELOAD_RECOVER_FLAG = "sw-hard-reload-recover";

export async function ensureEncryptionServiceWorker(): Promise<ServiceWorker | null> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
    return null;
  }
  // Already controlled by an active worker? Reuse it — the install /
  // activate handlers self-claim, so the very first visit ends up here
  // too, just one navigation tick later than subsequent visits.
  const existing = await navigator.serviceWorker.getRegistration("/");
  const reg = existing ?? (await navigator.serviceWorker.register("/sw.js", {
    scope: "/",
  }));
  await navigator.serviceWorker.ready;
  // .controller can still be null on the very first registration in this
  // tab. Wait for the controllerchange event in that case so the page
  // doesn't try to postMessage before there's a recipient. Bounded so a
  // worker that never claims doesn't trap the caller forever — null lets
  // DownloadView fall through to its error state.
  if (!navigator.serviceWorker.controller) {
    const controlled = await new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => resolve(false), CONTROLLER_WAIT_MS);
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        () => {
          clearTimeout(timer);
          resolve(true);
        },
        { once: true },
      );
      // Belt-and-suspenders: if claim has already happened, the event
      // won't fire — re-check after a short tick.
      setTimeout(() => {
        if (navigator.serviceWorker.controller) {
          clearTimeout(timer);
          resolve(true);
        }
      }, 100);
    });
    if (!controlled && !navigator.serviceWorker.controller) {
      // Hard-reload recovery: an active registration with no controller
      // is the signature of Ctrl+Shift+R. Reload once so the next
      // navigation goes through the SW; the sessionStorage flag stops
      // us from looping if the SW is genuinely broken. The flag is
      // cleared on any code path that ends up with a real controller
      // (see below), so a subsequent legitimate hard-reload gets its
      // one recovery attempt too. sessionStorage access is wrapped
      // because some privacy modes throw on read/write.
      let alreadyAttempted = false;
      try {
        alreadyAttempted = !!sessionStorage.getItem(HARD_RELOAD_RECOVER_FLAG);
      } catch {
        // Storage is inaccessible; treat as "no prior attempt" and skip
        // the reload entirely to avoid a loop we can't detect.
        alreadyAttempted = true;
      }
      if (reg.active && !alreadyAttempted) {
        try {
          sessionStorage.setItem(HARD_RELOAD_RECOVER_FLAG, "1");
        } catch {
          return null;
        }
        window.location.reload();
        // Hold the promise open until the reload navigation actually
        // preempts execution — returning here would let the caller
        // synchronously flip to the ``error`` state and paint one
        // frame of "decryption unavailable" before the reload lands.
        return new Promise<ServiceWorker | null>(() => {});
      }
      return null;
    }
  }
  // We ended up with a controller — clear the recovery flag so a future
  // hard-reload in this tab gets its own single retry.
  try {
    sessionStorage.removeItem(HARD_RELOAD_RECOVER_FLAG);
  } catch {
    // Ignored — flag stays set, we just miss the reset. A future hard-
    // reload would forgo its one retry, no worse than today's behavior.
  }
  return navigator.serviceWorker.controller ?? reg.active ?? null;
}

export async function registerEncryptionKey(
  sw: ServiceWorker,
  token: string,
  keyFragment: string,
  files: DownloadTransferFile[],
  chunkSize: number,
): Promise<void> {
  const keyBytes = base64UrlDecode(keyFragment);
  const filesPayload: ServiceWorkerFilePayload[] = files.map((f) => ({
    id: f.id,
    plaintextSize: f.plaintext_size ?? f.size,
    chunkSize,
    filename: f.filename,
    mimeType: f.mime_type || "application/octet-stream",
  }));

  // In dev the backend (:8981) and the frontend (:8980) live on different
  // origins, so the SW can't use a relative /api path — it'd resolve to
  // the Vite server, which has no API. NEXT_PUBLIC_API_ORIGIN holds the
  // absolute backend URL when set; in prod it's typically empty (Caddy
  // proxies /api/* to the backend same-origin) and we send "" so the SW
  // falls back to a relative path.
  const apiOrigin =
    (import.meta.env.NEXT_PUBLIC_API_ORIGIN as string | undefined) ?? "";

  await new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      navigator.serviceWorker.removeEventListener("message", listener);
      clearTimeout(timer);
    };
    const listener = (event: MessageEvent) => {
      if (!event.data || event.data.token !== token) return;
      if (event.data.type === "encryption-register-ack") {
        cleanup();
        resolve();
      } else if (event.data.type === "encryption-register-error") {
        cleanup();
        reject(
          new Error(
            typeof event.data.message === "string"
              ? event.data.message
              : "SW key registration failed",
          ),
        );
      }
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("SW key registration timed out"));
    }, REGISTER_ACK_WAIT_MS);
    navigator.serviceWorker.addEventListener("message", listener);
    sw.postMessage({
      type: "encryption-register",
      token,
      keyBytes,
      files: filesPayload,
      apiOrigin,
    });
  });
}

// Best-effort key drop on unmount: tells the SW to forget this transfer's
// key so it doesn't sit in worker memory after the user navigates away.
// Failure to post is harmless — the worker will be terminated by the
// browser eventually, and a fresh page load re-registers from scratch.
export function unregisterEncryptionKey(token: string): void {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
    return;
  }
  try {
    navigator.serviceWorker.controller?.postMessage({
      type: "encryption-unregister",
      token,
    });
  } catch {
    // The worker may have been terminated between the controller lookup
    // and the postMessage; nothing to do.
  }
}

// URL the SW intercepts to stream the decrypted bytes. The filename
// segment is decorative (Content-Disposition is set by the SW), but
// included so the browser's default suggestion is usable if a user
// right-clicks "Save As".
export function streamingDownloadUrl(
  token: string,
  fileId: string,
  filename: string,
): string {
  return `/_dl/${token}/${fileId}/${encodeURIComponent(filename)}`;
}
