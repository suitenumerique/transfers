import Link from "next/link";
import { useTranslation } from "react-i18next";
import type { TransferListItem } from "@/features/api/types";
import { TransferStatusBadge } from "./TransferStatusBadge";
import { formatFileSize } from "@/features/utils/string-helper";

export function TransferCard({ transfer }: { transfer: TransferListItem }) {
  const { t } = useTranslation();

  const date = new Date(transfer.created_at).toLocaleDateString("fr-FR", {
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
        <TransferStatusBadge status={transfer.status} />
      </div>
      <div className="transfer-card__meta">
        <span>{t("{{count}} file", { count: transfer.file_count })}</span>
        <span>{formatFileSize(transfer.total_size)}</span>
        <span>{t("{{count}} recipient", { count: transfer.recipient_count })}</span>
        <span>{date}</span>
      </div>
    </Link>
  );
}
