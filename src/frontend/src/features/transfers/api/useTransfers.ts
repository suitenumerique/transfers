import {
  keepPreviousData,
  useInfiniteQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import type { PaginatedResponse, TransferListItem } from "@/features/api/types";

interface UseTransfersParams {
  // Omitted: every status (the deposit lists show expired ones muted).
  deactivated?: boolean;
  search?: string;
  // Extra list filters, e.g. ``{ direction: "inbound", inbox: "true" }``.
  filters?: Record<string, string>;
}

// Fetch in chunks large enough that a fast wheel/trackpad flick doesn't
// run through an entire page in a single tick.
const PAGE_SIZE = 50;

function buildUrl({ deactivated, search, filters, page }: UseTransfersParams & { page: number }) {
  const params = new URLSearchParams({
    ...filters,
    page: String(page),
    page_size: String(PAGE_SIZE),
  });
  if (deactivated !== undefined) {
    params.set("deactivated", String(deactivated));
  }
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

export function useTransfers({ deactivated, search, filters }: UseTransfersParams) {
  return useInfiniteQuery({
    queryKey: ["transfers", { deactivated, search: search || "", filters }],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      apiFetch<PaginatedResponse<TransferListItem>>(
        buildUrl({ deactivated, search, filters, page: pageParam as number }),
      ),
    getNextPageParam: (last) => extractNextPage(last.next),
    // Each keystroke of a search is a new query: keep the previous rows
    // until its results arrive, rather than emptying the list meanwhile.
    placeholderData: keepPreviousData,
  });
}

// Invalidate both the active and deactivated sections after a mutation.
// Matching on the root ``["transfers"]`` key catches every param combo.
export function useInvalidateTransfers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["transfers"] });
}
