import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { PaginatedResponse, TransferListItem } from "@/features/api/types";

export function useTransfers(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["transfers", { page, pageSize }],
    queryFn: () =>
      apiFetch<PaginatedResponse<TransferListItem>>(
        `/transfers/?page=${page}&page_size=${pageSize}`,
      ),
  });
}
