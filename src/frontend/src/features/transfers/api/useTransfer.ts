import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

export function useTransfer(id: string | undefined) {
  return useQuery({
    queryKey: ["transfers", id],
    queryFn: () => apiFetch<TransferDetail>(`/transfers/${id}/`),
    enabled: !!id,
  });
}
