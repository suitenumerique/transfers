import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";

// Hard-delete a deactivated transfer, or a deposit in any state. The
// backend refuses a sent transfer that is still ACTIVE (its link is live),
// so a 400 there means the caller shouldn't have offered the button.
// On success the ``Transfer`` row and its FK-linked children (files,
// recipients) are gone, so any detail view or list entry pointing at this
// id becomes unavailable — invalidate both queries so the UI drops the
// cached view. Retained ``TransferEvent`` audit records live on
// separately by design; the Transfer detail is what disappears here.
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
