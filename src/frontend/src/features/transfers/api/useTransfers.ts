import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { PaginatedResponse, TransferListItem } from "@/features/api/types";

export function useTransfers(page = 1) {
  return useQuery({
    queryKey: ["transfers", { page }],
    queryFn: () =>
      apiFetch<PaginatedResponse<TransferListItem>>(
        `/transfers/?page=${page}`,
      ),
  });
}
