import { useTranslation } from "react-i18next";
import { Badge } from "@/features/ui/components/badge";

const STATUS_MAP = {
  active: { labelKey: "Active", color: "success" as const },
  expired: { labelKey: "Expired", color: "warning" as const },
  revoked: { labelKey: "Revoked", color: "error" as const },
};

export function TransferStatusBadge({
  status,
}: {
  status: "active" | "expired" | "revoked";
}) {
  const { t } = useTranslation();
  const { labelKey, color } = STATUS_MAP[status];
  return <Badge color={color}>{t(labelKey)}</Badge>;
}
