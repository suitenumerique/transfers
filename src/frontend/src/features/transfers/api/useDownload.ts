import { useQuery } from "@tanstack/react-query";
import { apiFetch, apiUrl } from "@/features/api/client";
import type { DownloadTransferFull } from "@/features/api/types";

export function useDownloadTransfer(token: string | undefined) {
  return useQuery({
    queryKey: ["downloads", token],
    queryFn: () => apiFetch<DownloadTransferFull>(`/downloads/${token}/`),
    enabled: !!token,
    retry: false,
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
