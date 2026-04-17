import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  DeleteConfirmationModal,
  Input,
  VariantType,
  useModal,
} from "@gouvfr-lasuite/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import type { TransferDetail as TransferDetailType } from "@/features/api/types";
import { useRevokeTransfer } from "../api/useRevokeTransfer";
import { consumePassword } from "../utils/passwordStash";
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
  const [passwordCopied, setPasswordCopied] = useState(false);
  const revokeModal = useModal();
  // Consumed once on mount: cleartext password is only available right
  // after creation, never again.
  const oneShotPassword = useMemo(
    () => consumePassword(transfer.id),
    [transfer.id],
  );

  const downloadUrl = transfer.public_token
    ? `${window.location.origin}/t/${transfer.public_token}`
    : "";

  const copyLink = async () => {
    await navigator.clipboard.writeText(downloadUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRevokeDecision = (decision?: string | null) => {
    revokeModal.close();
    if (decision === "delete") {
      revokeTransfer.mutate(transfer.id);
    }
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

  const copyPassword = async () => {
    if (!oneShotPassword) return;
    await navigator.clipboard.writeText(oneShotPassword);
    setPasswordCopied(true);
    setTimeout(() => setPasswordCopied(false), 2000);
  };

  return (
    <div className="transfer-detail">
      <div className="transfer-detail__header">
        <h1>{transfer.title || t("Untitled")}</h1>
        <TransferStatusBadge status={transfer.status} />
        {transfer.has_password && (
          <span
            className="transfer-detail__password-badge"
            title={t("Password protected")}
          >
            🔒 {t("Password protected")}
          </span>
        )}
      </div>

      <div className="transfer-detail__meta">
        <span>{t("Created on {{date}}", { date: createdAt })}</span>
        <span>{t("Expires on {{date}}", { date: expiresAt })}</span>
      </div>

      {oneShotPassword && (
        <Alert type={VariantType.WARNING} className="transfer-detail__one-shot">
          <div className="transfer-detail__one-shot-body">
            <strong>{t("Password to share")}</strong>
            <Input
              label={t("Password to share")}
              hideLabel
              value={oneShotPassword}
              readOnly
              fullWidth
              rightIcon={
                <button
                  type="button"
                  className="transfer-form__password-action"
                  onClick={copyPassword}
                  aria-label={t("Copy password")}
                  title={t("Copy password")}
                >
                  <Icon name={passwordCopied ? "check" : "content_copy"} />
                </button>
              }
            />
            <p className="transfer-detail__one-shot-warning">
              {t(
                "This password will never be shown again. Share it with the recipient separately from the link.",
              )}
            </p>
          </div>
        </Alert>
      )}

      <div className="transfer-detail__actions">
        {transfer.status === "active" && (
          <>
            <Button size="small" onClick={copyLink}>
              {copied ? t("Link copied!") : t("Copy link")}
            </Button>
            <Button
              size="small"
              color="error"
              onClick={revokeModal.open}
              disabled={revokeTransfer.isPending}
            >
              {t("Revoke")}
            </Button>
          </>
        )}
      </div>

      {transfer.sharing_mode === "email" && transfer.recipients.length > 0 && (
        <section className="transfer-detail__section">
          <h2>{t("Recipients ({{count}})", { count: transfer.recipients.length })}</h2>
          <ul className="transfer-detail__recipients">
            {transfer.recipients.map((r) => (
              <li key={r.id} className="transfer-detail__recipient">
                <span>{r.email}</span>
                <span className={`transfer-detail__recipient-status${r.email_sent_at ? "" : " transfer-detail__recipient-status--pending"}`}>
                  {r.email_sent_at ? "✓" : "●"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

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

      <DeleteConfirmationModal
        isOpen={revokeModal.isOpen}
        onClose={revokeModal.close}
        onDecide={handleRevokeDecision}
        title={t("Confirm revoke")}
      >
        {t("This link will no longer work and files will be deleted.")}
      </DeleteConfirmationModal>
    </div>
  );
}
