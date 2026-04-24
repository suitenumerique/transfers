import { useTranslation } from "react-i18next";
import { Badge } from "@gouvfr-lasuite/ui-kit";

import type { TransferStatus } from "@/features/api/types";

// pending_file_deletion shares the "deactivated" look with deactivated:
// from the agent's point of view the transfer is already dead (link
// closed). The remaining S3 purge is communicated in the meta line, not
// the badge, so we keep the badge honest and uniform across terminal
// states.
const STATUS_MAP: Record<
  TransferStatus,
  { labelKey: string; type: "success" | "warning" | "danger" }
> = {
  active: { labelKey: "Active", type: "success" },
  pending_file_deletion: { labelKey: "Deactivated", type: "danger" },
  deactivated: { labelKey: "Deactivated", type: "danger" },
};

export function TransferStatusBadge({ status }: { status: TransferStatus }) {
  const { t } = useTranslation();
  const { labelKey, type } = STATUS_MAP[status];
  return <Badge type={type}>{t(labelKey)}</Badge>;
}
