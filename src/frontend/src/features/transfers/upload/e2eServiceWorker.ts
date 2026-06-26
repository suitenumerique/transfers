// Helpers for the recipient side of E2E: register the decryption SW and
// hand it the per-file metadata + the AES key extracted from the URL
// fragment. The SW lives at /sw.js (scope /) and intercepts /_dl/...
// requests to stream-decrypt the ciphertext into the native download
// manager.

import type { DownloadTransferFile } from "@/features/api/types";
import { base64UrlDecode } from "./e2eCrypto";

export interface ServiceWorkerFilePayload {
  id: string;
  plaintextSize: number;
  chunkSize: number;
  filename: string;
  mimeType: string;
}

export async function ensureE2eServiceWorker(): Promise<ServiceWorker | null> {
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
  // doesn't try to postMessage before there's a recipient.
  if (!navigator.serviceWorker.controller) {
    await new Promise<void>((resolve) => {
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        () => resolve(),
        { once: true },
      );
      // Belt-and-suspenders: if claim has already happened, the event
      // won't fire — re-check after a short tick.
      setTimeout(() => {
        if (navigator.serviceWorker.controller) resolve();
      }, 100);
    });
  }
  return navigator.serviceWorker.controller ?? reg.active ?? null;
}

export async function registerE2eKey(
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

  await new Promise<void>((resolve) => {
    const listener = (event: MessageEvent) => {
      if (
        event.data &&
        event.data.type === "e2e-register-ack" &&
        event.data.token === token
      ) {
        navigator.serviceWorker.removeEventListener("message", listener);
        resolve();
      }
    };
    navigator.serviceWorker.addEventListener("message", listener);
    sw.postMessage({
      type: "e2e-register",
      token,
      keyBytes,
      files: filesPayload,
      apiOrigin,
    });
  });
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
