import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { DepositSpace, DepositSpaceSettings } from "@/features/api/types";
import { rememberSpaceKey } from "../spaces";

// ``key``: an end-to-end space's key, kept in this browser and never sent.
// Saved here rather than by the page, which may be gone by the answer.
type NewSpace = DepositSpaceSettings & { name: string; key?: string | null };

export function useCreateDepositSpace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (space: NewSpace) => {
      const body: Partial<NewSpace> = { ...space };
      delete body.key;
      return apiFetch<DepositSpace>("/deposit-spaces/", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: (space, { key }) => {
      if (key) rememberSpaceKey(space.id, key);
      queryClient.invalidateQueries({ queryKey: ["deposit-spaces"] });
    },
  });
}
