import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

export function useReactivateTransfer() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<TransferDetail>(`/transfers/${id}/reactivate/`, {
        method: "POST",
      }),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      queryClient.invalidateQueries({ queryKey: ["transfers", id] });
    },
  });
}
