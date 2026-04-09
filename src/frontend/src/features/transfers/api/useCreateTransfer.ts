import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

interface CreateTransferInput {
  title: string;
  message: string;
  password: string;
  expires_in_days: number;
  recipients: string[];
  files: File[];
}

export function useCreateTransfer() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: CreateTransferInput) => {
      const formData = new FormData();
      if (input.title) formData.append("title", input.title);
      if (input.message) formData.append("message", input.message);
      if (input.password) formData.append("password", input.password);
      formData.append("expires_in_days", String(input.expires_in_days));

      input.recipients.forEach((email) => {
        formData.append("recipients", email);
      });
      input.files.forEach((file) => {
        formData.append("files", file);
      });

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
