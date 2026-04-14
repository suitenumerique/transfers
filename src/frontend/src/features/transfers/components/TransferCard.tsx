import Link from "next/link";
import { useTranslation } from "react-i18next";
import type { TransferListItem } from "@/features/api/types";
import { TransferStatusBadge } from "./TransferStatusBadge";
import { formatFileSize } from "@/features/utils/string-helper";

export function TransferCard({ transfer }: { transfer: TransferListItem }) {
  const { t } = useTranslation();

  const expiresAt = new Date(transfer.expires_at).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  return (
    <Link href={`/transfers/${transfer.id}`} className="transfer-card">
      <div className="transfer-card__header">
        <span className="transfer-card__title">
          {transfer.title || t("Untitled")}
        </span>
        {transfer.has_password && (
          <span title={t("Password protected")} aria-label={t("Password protected")}>
            🔒
          </span>
        )}
        <TransferStatusBadge status={transfer.status} />
      </div>
      <div className="transfer-card__meta">
        <span>{transfer.filename}</span>
        <span>{formatFileSize(transfer.filesize)}</span>
        <span>{expiresAt}</span>
        <span>{transfer.consulted ? "✓" : "—"} {t("Consulted")}</span>
        <span>{transfer.downloaded ? "✓" : "—"} {t("Downloaded")}</span>
      </div>
    </Link>
  );
}
