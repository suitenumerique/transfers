import { useQuery } from "@tanstack/react-query";
import { apiFetch, apiUrl } from "@/features/api/client";
import type { DownloadTransferFull } from "@/features/api/types";

export function useDownloadTransfer(token: string | undefined) {
  return useQuery({
    queryKey: ["downloads", token],
    queryFn: () => apiFetch<DownloadTransferFull>(`/downloads/${token}/`),
    enabled: !!token,
  });
}

export function getFileDownloadUrl(
  token: string,
  fileId: string,
): string {
  return apiUrl(`/downloads/${token}/files/${fileId}/download/`);
}
