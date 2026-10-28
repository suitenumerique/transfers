import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { DepositSpace, PaginatedResponse } from "@/features/api/types";

// An agent's deposit spaces, open ones first, every page of them: the
// spaces page and the sidebar show them all.
export function useDepositSpaces() {
  return useQuery({
    queryKey: ["deposit-spaces"],
    queryFn: async () => {
      const results: DepositSpace[] = [];
      for (let page = 1; ; page++) {
        const data = await apiFetch<PaginatedResponse<DepositSpace>>(
          `/deposit-spaces/?page=${page}&page_size=100`,
        );
        results.push(...data.results);
        if (!data.next) return { ...data, next: null, results };
      }
    },
  });
}
