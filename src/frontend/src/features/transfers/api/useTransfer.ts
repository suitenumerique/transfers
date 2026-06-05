import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

export function useTransfer(id: string | undefined) {
  return useQuery({
    queryKey: ["transfers", id],
    queryFn: () => apiFetch<TransferDetail>(`/transfers/${id}/`),
    enabled: !!id,
    // While any file is still being scanned for viruses, poll so the
    // sender's recap flips from "scanning…" to clean/blocked on its own —
    // mirrors the recipient-side useDownloadTransfer poll. Stops once every
    // file has reached a terminal scan state.
    refetchInterval: (query) => {
      const data = query.state.data as TransferDetail | undefined;
      const stillScanning = data?.files.some((f) => f.scan_status === "pending");
      return stillScanning ? 3000 : false;
    },
  });
}
