import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { DepositSpace } from "@/features/api/types";

export function useCreateDepositSpace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; retention_days: number }) =>
      apiFetch<DepositSpace>("/deposit-spaces/", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deposit-spaces"] });
    },
  });
}
