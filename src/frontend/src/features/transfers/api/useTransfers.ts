import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { PaginatedResponse, TransferListItem } from "@/features/api/types";

interface UseTransfersParams {
  deactivated: boolean;
  search?: string;
}

// Fetch in chunks large enough that a fast wheel/trackpad flick doesn't
// run through an entire page in a single tick.
const PAGE_SIZE = 50;

function buildUrl({ deactivated, search, page }: UseTransfersParams & { page: number }) {
  const params = new URLSearchParams({
    deactivated: String(deactivated),
    page: String(page),
    page_size: String(PAGE_SIZE),
  });
  if (search) {
    params.set("search", search);
  }
  return `/transfers/?${params.toString()}`;
}

// DRF's ``next`` is an absolute URL like ``http://host/api/v1.0/transfers/?page=3``.
// We only need the ``page`` param for the next fetch.
function extractNextPage(next: string | null): number | undefined {
  if (!next) return undefined;
  const page = new URL(next).searchParams.get("page");
  return page ? Number(page) : undefined;
}

export function useTransfers({ deactivated, search }: UseTransfersParams) {
  return useInfiniteQuery({
    queryKey: ["transfers", { deactivated, search: search || "" }],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      apiFetch<PaginatedResponse<TransferListItem>>(
        buildUrl({ deactivated, search, page: pageParam as number }),
      ),
    getNextPageParam: (last) => extractNextPage(last.next),
  });
}

// Invalidate both the active and deactivated sections after a mutation.
// Matching on the root ``["transfers"]`` key catches every param combo.
export function useInvalidateTransfers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["transfers"] });
}
