import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

export function useRenameTransfer(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (title: string) =>
      apiFetch<TransferDetail>(`/transfers/${id}/`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      }),
    onSuccess: () => {
      // The detail page and every sidebar list show the title.
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}
