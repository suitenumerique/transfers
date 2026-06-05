import { useQuery } from "@tanstack/react-query";
import { apiFetch, apiUrl } from "@/features/api/client";
import type { DownloadTransferFull } from "@/features/api/types";

export function useDownloadTransfer(token: string | undefined) {
  return useQuery({
    queryKey: ["downloads", token],
    queryFn: () => apiFetch<DownloadTransferFull>(`/downloads/${token}/`),
    enabled: !!token,
    retry: false,
    // While any file is still being scanned for viruses, poll so the UI
    // flips from "scanning…" to a downloadable state without a manual
    // refresh. Stop polling once every file has reached a terminal state.
    refetchInterval: (query) => {
      const data = query.state.data as DownloadTransferFull | undefined;
      const stillScanning = data?.files.some((f) => f.scan_status === "pending");
      return stillScanning ? 3000 : false;
    },
  });
}

// Triggers a download by navigating to the backend endpoint, which 302s to a
// presigned S3 URL. The browser sees the response's Content-Disposition:
// attachment header (baked into the presigned URL) and hands off to its
// native download manager — the current page stays put, no blob is buffered
// in memory, and large files stream straight from S3 to disk.
export function downloadFile(token: string, fileId: string): void {
  const a = document.createElement("a");
  a.href = apiUrl(`/downloads/${token}/files/${fileId}/download/`);
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// Same shape as ``downloadFile`` but uses a hidden iframe rather than an
// anchor click. Browsers block silent anchor-click downloads after the
// first when several fire in quick succession (the "site tries to download
// multiple files" prompt) — iframe loads aren't subject to the same
// gesture-bound throttling, which makes them the right tool for the
// "Download all" loop. The iframe is yanked after 5s, by which point the
// browser has taken over the streaming.
export function downloadFileInIframe(token: string, fileId: string): void {
  const iframe = document.createElement("iframe");
  iframe.style.display = "none";
  iframe.src = apiUrl(`/downloads/${token}/files/${fileId}/download/`);
  document.body.appendChild(iframe);
  setTimeout(() => iframe.remove(), 5000);
}
