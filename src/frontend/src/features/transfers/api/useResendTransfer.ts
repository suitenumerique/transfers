import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { TransferDetail } from "@/features/api/types";

// Re-send the recipient invitation emails for an email-mode transfer.
// The backend resets `email_sent_at` on every recipient and re-queues
// `send_recipient_invitations_task`.
export function useResendTransfer() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<TransferDetail>(`/transfers/${id}/resend/`, {
        method: "POST",
      }),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ["transfers", id, "events"] });
    },
  });
}
