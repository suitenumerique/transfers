import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { DepositSpace } from "@/features/api/types";

export function useDepositSpace(id: string | undefined) {
  return useQuery({
    queryKey: ["deposit-spaces", id],
    queryFn: () => apiFetch<DepositSpace>(`/deposit-spaces/${id}/`),
    enabled: !!id,
  });
}
