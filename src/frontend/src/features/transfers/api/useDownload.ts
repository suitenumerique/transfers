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

// Fetches a file as a blob and triggers a programmatic download.
export async function downloadFile(
  token: string,
  fileId: string,
  filename: string,
): Promise<void> {
  const url = apiUrl(`/downloads/${token}/files/${fileId}/download/`);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Download failed: ${res.status}`);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}
