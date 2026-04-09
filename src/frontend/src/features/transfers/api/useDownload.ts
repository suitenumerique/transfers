import { useQuery, useMutation } from "@tanstack/react-query";
import { apiFetch, apiUrl } from "@/features/api/client";
import type {
  DownloadTransferResponse,
  DownloadTransferFull,
} from "@/features/api/types";

export function useDownloadTransfer(token: string | undefined) {
  return useQuery({
    queryKey: ["downloads", token],
    queryFn: () =>
      apiFetch<DownloadTransferResponse>(`/downloads/${token}/`),
    enabled: !!token,
  });
}

export function useVerifyPassword(token: string) {
  return useMutation({
    mutationFn: (password: string) =>
      apiFetch<DownloadTransferFull>(`/downloads/${token}/verify-password/`, {
        method: "POST",
        body: JSON.stringify({ password }),
      }),
  });
}

export function getFileDownloadUrl(
  token: string,
  fileId: string,
  password?: string,
): string {
  const base = apiUrl(`/downloads/${token}/files/${fileId}/download/`);
  return password ? `${base}?password=${encodeURIComponent(password)}` : base;
}

export function getDownloadAllUrl(
  token: string,
  password?: string,
): string {
  const base = apiUrl(`/downloads/${token}/download-all/`);
  return password ? `${base}?password=${encodeURIComponent(password)}` : base;
}
