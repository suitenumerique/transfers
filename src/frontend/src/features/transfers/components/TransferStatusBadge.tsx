import { useTranslation } from "react-i18next";
import { Badge } from "@gouvfr-lasuite/ui-kit";

const STATUS_MAP = {
  active: { labelKey: "Active", type: "success" as const },
  expired: { labelKey: "Expired", type: "warning" as const },
  revoked: { labelKey: "Revoked", type: "danger" as const },
};

export function TransferStatusBadge({
  status,
}: {
  status: "active" | "expired" | "revoked";
}) {
  const { t } = useTranslation();
  const { labelKey, type } = STATUS_MAP[status];
  return <Badge type={type}>{t(labelKey)}</Badge>;
}
