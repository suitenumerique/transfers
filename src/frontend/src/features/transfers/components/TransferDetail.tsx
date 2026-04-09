import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import type { TransferDetail as TransferDetailType } from "@/features/api/types";
import { useRevokeTransfer } from "../api/useRevokeTransfer";
import { TransferStatusBadge } from "./TransferStatusBadge";
import { formatFileSize } from "@/features/utils/string-helper";

export function TransferDetail({
  transfer,
}: {
  transfer: TransferDetailType;
}) {
  const { t } = useTranslation();
  const revokeTransfer = useRevokeTransfer();
  const [copied, setCopied] = useState(false);

  const downloadUrl = `${window.location.origin}/t/${transfer.public_token}`;

  const copyLink = async () => {
    await navigator.clipboard.writeText(downloadUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRevoke = () => {
    if (!confirm(t("Confirm revoke"))) return;
    revokeTransfer.mutate(transfer.id);
  };

  const expiresAt = new Date(transfer.expires_at).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  const createdAt = new Date(transfer.created_at).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  return (
    <div className="transfer-detail">
      <div className="transfer-detail__header">
        <h1>{transfer.title || t("Untitled")}</h1>
        <TransferStatusBadge status={transfer.status} />
      </div>

      {transfer.message && (
        <p className="transfer-detail__message">{transfer.message}</p>
      )}

      <div className="transfer-detail__meta">
        <span>{t("Created on {{date}}", { date: createdAt })}</span>
        <span>{t("Expires on {{date}}", { date: expiresAt })}</span>
        {transfer.has_password && <span>{t("Password protected")}</span>}
      </div>

      <div className="transfer-detail__actions">
        <Button size="small" onClick={copyLink}>
          {copied ? t("Link copied!") : t("Copy link")}
        </Button>
        {transfer.status === "active" && (
          <Button
            size="small"
            color="neutral"
            onClick={handleRevoke}
            disabled={revokeTransfer.isPending}
          >
            {t("Revoke")}
          </Button>
        )}
      </div>

      <section className="transfer-detail__section">
        <h2>{t("Files ({{count}})", { count: transfer.files.length })}</h2>
        <ul className="transfer-detail__files">
          {transfer.files.map((file) => (
            <li key={file.id}>
              <span>{file.filename}</span>
              <span className="transfer-detail__file-size">
                {formatFileSize(file.size)}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="transfer-detail__section">
        <h2>{t("Recipients ({{count}})", { count: transfer.recipients.length })}</h2>
        <ul className="transfer-detail__recipients">
          {transfer.recipients.map((r) => (
            <li key={r.id}>{r.email}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
