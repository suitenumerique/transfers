import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  DeleteConfirmationModal,
  Loader,
  useModal,
} from "@gouvfr-lasuite/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import type { TransferDetail as TransferDetailType } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { useRevokeTransfer } from "../api/useRevokeTransfer";
import { useTransferEvents } from "../api/useTransferEvents";
import { TransferStatusBadge } from "./TransferStatusBadge";

const EVENT_LABELS: Record<string, string> = {
  transfer_created: "Transfer created",
  email_sent: "Notification email sent",
  link_opened: "Link opened",
  file_downloaded: "File downloaded",
  transfer_revoked: "Transfer revoked",
  transfer_expired: "Transfer expired",
  files_deleted: "Files deleted",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function TransferDetail({
  transfer,
}: {
  transfer: TransferDetailType;
}) {
  const { t } = useTranslation();
  const revokeTransfer = useRevokeTransfer();
  const [copied, setCopied] = useState(false);
  const revokeModal = useModal();
  const events = useTransferEvents(transfer.id);

  const downloadUrl = transfer.public_token
    ? `${window.location.origin}/t/${transfer.public_token}`
    : "";

  const copyLink = async () => {
    if (!downloadUrl) return;
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

  const totalSize = transfer.files.reduce((sum, f) => sum + f.size, 0);
  const isPublicLink = transfer.sharing_mode === "link";

  return (
    <div className="transfer-detail">
      <div className="transfer-detail__header">
        <h1 className="transfer-detail__title">
          {transfer.title || t("Untitled")}
        </h1>
        {transfer.status !== "active" && (
          <TransferStatusBadge status={transfer.status} />
        )}
      </div>

      <div className="transfer-detail__meta">
        <span className="transfer-detail__meta-item">
          <Icon name={isPublicLink ? "public" : "lock"} />
          {isPublicLink ? t("Public link") : t("Private")}
        </span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>{t("Expires on {{date}}", { date: expiresAt })}</span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>
          {t("{{count}} item", { count: transfer.files.length })}
        </span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>{formatFileSize(totalSize)}</span>
      </div>

      {downloadUrl && (
        <div className="transfer-detail__link-box">
          <span className="transfer-detail__link-url">{downloadUrl}</span>
          <button
            type="button"
            className="transfer-detail__link-copy"
            onClick={copyLink}
            title={copied ? t("Link copied!") : t("Copy link")}
            aria-label={copied ? t("Link copied!") : t("Copy link")}
          >
            <Icon name={copied ? "check_circle" : "content_copy"} />
          </button>
        </div>
      )}

      <ul
        className="transfer-detail__file-list"
        aria-label={t("Files ({{count}})", { count: transfer.files.length })}
      >
        {transfer.files.map((file) => (
          <li key={file.id} className="transfer-detail__file-item">
            <span
              className="transfer-detail__file-icon-tile"
              aria-hidden="true"
            >
              <Icon name="description" />
            </span>
            <span className="transfer-detail__file-label">
              {file.filename}
              <span className="transfer-detail__file-sep">·</span>
              {formatFileSize(file.size)}
            </span>
          </li>
        ))}
      </ul>

      {transfer.status === "active" && (
        <div className="transfer-detail__actions">
          <Button
            onClick={copyLink}
            icon={
              <Icon name={copied ? "check_circle" : "content_copy"} />
            }
          >
            {copied ? t("Link copied!") : t("Copy link")}
          </Button>
          <Button
            variant="secondary"
            className="transfer-detail__revoke-btn"
            onClick={revokeModal.open}
            disabled={revokeTransfer.isPending}
          >
            {t("Revoke")}
          </Button>
        </div>
      )}

      {transfer.sharing_mode === "email" && transfer.recipients.length > 0 && (
        <section className="transfer-detail__section">
          <h2>
            {t("Recipients ({{count}})", {
              count: transfer.recipients.length,
            })}
          </h2>
          <ul className="transfer-detail__recipients">
            {transfer.recipients.map((r) => (
              <li key={r.id} className="transfer-detail__recipient">
                <span>{r.email}</span>
                <span
                  className={`transfer-detail__recipient-status${
                    r.email_sent_at
                      ? ""
                      : " transfer-detail__recipient-status--pending"
                  }`}
                >
                  {r.email_sent_at ? "✓" : "●"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="transfer-detail__history">
        <h2 className="transfer-detail__history-title">{t("Activity")}</h2>
        {events.isLoading ? (
          <Loader aria-label={t("Loading...")} />
        ) : !events.data || events.data.results.length === 0 ? (
          <p className="transfer-detail__history-empty">
            {t("No activity yet.")}
          </p>
        ) : (
          <div className="transfer-detail__history-table">
            <div className="transfer-detail__history-head">
              <div>{t("Activity")}</div>
              <div>{t("Date")}</div>
              <div>{t("By")}</div>
            </div>
            {events.data.results.map((ev) => {
              const isDownload = ev.event_type === "file_downloaded";
              const label = t(EVENT_LABELS[ev.event_type] ?? ev.event_type);
              const by =
                ev.actor_type === "agent" ? t("You") : t("Recipient");
              return (
                <div key={ev.id} className="transfer-detail__history-row">
                  <div className="transfer-detail__history-activity">
                    <span
                      className={`transfer-detail__history-tile${
                        isDownload ? " transfer-detail__history-tile--success" : ""
                      }`}
                      aria-hidden="true"
                    >
                      <Icon
                        name={isDownload ? "download" : "folder"}
                      />
                    </span>
                    <span>{label}</span>
                  </div>
                  <div className="transfer-detail__history-date">
                    {formatDate(ev.created_at)}
                  </div>
                  <div className="transfer-detail__history-actor">{by}</div>
                </div>
              );
            })}
          </div>
        )}
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
