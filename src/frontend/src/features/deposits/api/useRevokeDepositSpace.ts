import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { DepositSpace } from "@/features/api/types";

export function useRevokeDepositSpace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<DepositSpace>(`/deposit-spaces/${id}/revoke/`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deposit-spaces"] });
    },
  });
}
