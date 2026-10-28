import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { DepositSpace, DepositSpaceSettings } from "@/features/api/types";

export function useUpdateDepositSpace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DepositSpaceSettings) =>
      apiFetch<DepositSpace>(`/deposit-spaces/${id}/`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: (space) => {
      // At once, so a next member edit starts from this list.
      queryClient.setQueryData(["deposit-spaces", id], space);
      queryClient.invalidateQueries({ queryKey: ["deposit-spaces"] });
    },
  });
}
