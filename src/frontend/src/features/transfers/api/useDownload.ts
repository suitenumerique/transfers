import { useQuery } from "@tanstack/react-query";
import { apiFetch, apiUrl } from "@/features/api/client";
import type { DownloadTransferFull } from "@/features/api/types";

function passwordHeader(password?: string | null): Record<string, string> {
  return password ? { Authorization: `Bearer ${password}` } : {};
}

export function useDownloadTransfer(
  token: string | undefined,
  password?: string | null,
) {
  return useQuery({
    queryKey: ["downloads", token, password ?? null],
    queryFn: () =>
      apiFetch<DownloadTransferFull>(`/downloads/${token}/`, {
        headers: passwordHeader(password),
      }),
    enabled: !!token,
    retry: false,
  });
}

// Fetches a file as a blob and triggers a programmatic download. Used so
// the password stays in an HTTP header instead of leaking into the URL bar,
// browser history, or server logs. Trade-off: the entire file is buffered in
// memory before the download starts. Acceptable for the V1 file sizes; revisit
// if/when the password feature meets large-file uploads.
export async function downloadFileWithPassword(
  token: string,
  fileId: string,
  filename: string,
  password?: string | null,
): Promise<void> {
  const url = apiUrl(`/downloads/${token}/files/${fileId}/download/`);
  const res = await fetch(url, {
    headers: passwordHeader(password),
  });
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
