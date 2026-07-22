import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";

// Hard-delete a fully-deactivated transfer. The backend refuses anything
// but ``DEACTIVATED`` rows (there's a live link on ACTIVE, and dropping the
// TransferFile rows while PENDING_FILE_DELETION would strand their S3
// keys), so a 400 here means the caller shouldn't have offered the button.
// On success the row and its history are gone — invalidate the list and
// the per-transfer query so the UI drops any cached view.
export function useHardDeleteTransfer() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<void>(`/transfers/${id}/`, {
        method: "DELETE",
      }),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ["transfers"] });
      queryClient.invalidateQueries({ queryKey: ["transfers", id] });
    },
  });
}
