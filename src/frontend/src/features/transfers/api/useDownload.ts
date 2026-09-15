import { useQuery } from "@tanstack/react-query";
import { apiFetch, apiUrl } from "@/features/api/client";
import type { DownloadTransferFull } from "@/features/api/types";

// Frontend origin + /t/<token> — the canonical shape of a recipient link,
// without the encryption fragment. Empty string when the transfer has no public
// token yet (never persisted) or when called outside a browser context
// (SSR / test environment without a jsdom window), so consumers can
// boolean-check it.
export function transferBaseUrl(publicToken: string | null | undefined): string {
  if (!publicToken || typeof window === "undefined") return "";
  return `${window.location.origin}/t/${publicToken}`;
}

// The emailed link carries ``?r=<recipient token>`` so the backend can
// attribute this visit's LINK_OPENED / FILE_DOWNLOADED events to one
// recipient (everyone shares the same public token). Forward it on every
// download-side call; a bare link simply has none.
export function withRecipient(path: string, recipientToken?: string): string {
  return recipientToken
    ? `${path}?r=${encodeURIComponent(recipientToken)}`
    : path;
}

export function useDownloadTransfer(
  token: string | undefined,
  recipientToken?: string,
) {
  return useQuery({
    queryKey: ["downloads", token, recipientToken ?? null],
    queryFn: () =>
      apiFetch<DownloadTransferFull>(
        withRecipient(`/downloads/${token}/`, recipientToken),
      ),
    enabled: !!token,
    retry: false,
  });
}

// Triggers a download by navigating to the backend endpoint, which 302s to a
// presigned S3 URL. The browser sees the response's Content-Disposition:
// attachment header (baked into the presigned URL) and hands off to its
// native download manager — the current page stays put, no blob is buffered
// in memory, and large files stream straight from S3 to disk.
export function downloadFile(
  token: string,
  fileId: string,
  recipientToken?: string,
): void {
  const a = document.createElement("a");
  a.href = apiUrl(
    withRecipient(`/downloads/${token}/files/${fileId}/download/`, recipientToken),
  );
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// Same shape as ``downloadFile`` but uses a hidden iframe rather than an
// anchor click. Browsers block silent anchor-click downloads after the
// first when several fire in quick succession (the "site tries to download
// multiple files" prompt) — iframe loads aren't subject to the same
// gesture-bound throttling, which makes them the right tool for the
// "Download all" loop. The iframe is yanked after 60s: the browser's
// native download manager takes over as soon as the 302 to S3's presigned
// URL comes back with Content-Disposition: attachment, which can take a
// few seconds on slow links / cold S3 regions. The old 5s window silently
// cancelled downloads whose first byte arrived late.
export function downloadFileInIframe(
  token: string,
  fileId: string,
  recipientToken?: string,
): void {
  const iframe = document.createElement("iframe");
  iframe.style.display = "none";
  iframe.src = apiUrl(
    withRecipient(`/downloads/${token}/files/${fileId}/download/`, recipientToken),
  );
  document.body.appendChild(iframe);
  setTimeout(() => iframe.remove(), 60_000);
}
