import { useTransfers } from "@/features/transfers/api/useTransfers";

// Deposits received: on one space (``spaceId``) or, without it, the
// anonymous sends of the inbox. Paginated like the sidebar lists.
export function useInboundTransfers(spaceId?: string) {
  return useTransfers({
    filters: spaceId
      ? { direction: "inbound", deposit_space: spaceId }
      : { direction: "inbound", inbox: "true" },
  });
}
