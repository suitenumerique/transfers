import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { DepositSpace } from "@/features/api/types";

export function useUpdateDepositSpace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      body: Partial<Pick<DepositSpace, "name" | "retention_days">>,
    ) =>
      apiFetch<DepositSpace>(`/deposit-spaces/${id}/`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deposit-spaces"] });
    },
  });
}
