import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

interface CreateTransferInput {
  title: string;
  expires_in_days: number;
  file: File;
}

export function useCreateTransfer() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: CreateTransferInput) => {
      const formData = new FormData();
      if (input.title) formData.append("title", input.title);
      formData.append("expires_in_days", String(input.expires_in_days));
      formData.append("file", input.file);

      return apiFetch<TransferDetail>("/transfers/", {
        method: "POST",
        body: formData,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
    },
  });
}
