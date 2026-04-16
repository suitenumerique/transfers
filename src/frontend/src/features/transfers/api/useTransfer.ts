import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

export function useTransfer(id: string | undefined) {
  return useQuery({
    queryKey: ["transfers", id],
    queryFn: () => apiFetch<TransferDetail>(`/transfers/${id}/`),
    enabled: !!id,
    refetchInterval: (query) => {
      const transfer = query.state.data;
      if (!transfer) return false;
      // Poll while there are recipients waiting for email delivery
      const pending = transfer.recipients?.some((r) => !r.email_sent_at);
      return pending ? 3000 : false;
    },
  });
}
