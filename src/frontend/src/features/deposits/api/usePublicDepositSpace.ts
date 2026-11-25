import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { PublicDepositSpace } from "@/features/api/types";

// What the public deposit page shows. No retry: a 404 / 410 is an answer.
export function usePublicDepositSpace(token: string) {
  return useQuery({
    queryKey: ["deposit-space-public", token],
    queryFn: () =>
      apiFetch<PublicDepositSpace>(`/public-deposit-spaces/${token}/`),
    retry: false,
  });
}
