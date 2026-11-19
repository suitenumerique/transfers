import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";

// Deletes the space and every deposit on it.
export function useDeleteDepositSpace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>(`/deposit-spaces/${id}/`, { method: "DELETE" }),
    // Even on failure: the space and its deposits may be closed already.
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["deposit-spaces"] });
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}
