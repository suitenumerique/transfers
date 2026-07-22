import { useTranslation } from "react-i18next";
import { Badge } from "@gouvfr-lasuite/ui-kit";

import type { TransferStatus } from "@/features/api/types";

// ``expiring`` is UI-only: the row is still ACTIVE server-side, but its
// ``expires_at`` has passed and the hourly cleanup task hasn't caught up.
// Kept a warning tone (yellow) rather than danger — the transfer is not
// closed, just in the grace window before the beat flips it.
//
// pending_file_deletion shares the "deactivated" look with deactivated:
// from the agent's point of view the transfer is already dead (link
// closed). The remaining S3 purge is communicated in the meta line, not
// the badge, so we keep the badge honest and uniform across terminal
// states.
type BadgeStatus = TransferStatus | "expiring";

const STATUS_MAP: Record<
  BadgeStatus,
  { labelKey: string; type: "success" | "warning" | "danger" }
> = {
  active: { labelKey: "Active", type: "success" },
  expiring: { labelKey: "Expiration pending", type: "warning" },
  pending_file_deletion: { labelKey: "Deactivated", type: "danger" },
  deactivated: { labelKey: "Deactivated", type: "danger" },
};

export function TransferStatusBadge({ status }: { status: BadgeStatus }) {
  const { t } = useTranslation();
  const { labelKey, type } = STATUS_MAP[status];
  return <Badge type={type}>{t(labelKey)}</Badge>;
}
