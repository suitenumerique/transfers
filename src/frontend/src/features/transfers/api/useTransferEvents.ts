import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { PaginatedResponse, TransferEvent } from "@/features/api/types";

export function useTransferEvents(id: string | undefined) {
  return useQuery({
    queryKey: ["transfers", id, "events"],
    queryFn: () =>
      apiFetch<PaginatedResponse<TransferEvent>>(
        `/transfers/${id}/events/`,
      ),
    enabled: !!id,
  });
}
