import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  DeleteConfirmationModal,
  Input,
  Loader,
  useModal,
} from "@gouvfr-lasuite/cunningham-react";
import {
  ArrowUpRight,
  Checkmark,
  ChevronDown,
  Clock,
  Copy,
  Doc,
  Download,
  Folder,
  Globe,
  Perso,
  UserAvatar,
} from "@gouvfr-lasuite/ui-kit";
import type { TransferDetail as TransferDetailType } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { downloadFile } from "../api/useDownload";
import { useResendTransfer } from "../api/useResendTransfer";
import { useRevokeTransfer } from "../api/useRevokeTransfer";
import { useTransferEvents } from "../api/useTransferEvents";
import { FileItem } from "./FileItem";
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

function formatActivityDate(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Turn "amed.benarfa@email.fr" into "Amed Ben Arfa" — purely cosmetic so the
// avatar picks a deterministic color per person. Falls back to the raw email
// when the local-part is uninformative (single segment, digits-only, etc.).
function displayNameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  if (!local) return email;
  const parts = local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1));
  return parts.length >= 2 ? parts.join(" ") : email;
}

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(0, Math.ceil(ms / (24 * 60 * 60 * 1000)));
}

export function TransferDetail({
  transfer,
}: {
  transfer: TransferDetailType;
}) {
  const { t } = useTranslation();
  const revokeTransfer = useRevokeTransfer();
  const resendTransfer = useResendTransfer();
  const [copied, setCopied] = useState(false);
  const [recipientsOpen, setRecipientsOpen] = useState(true);
  const revokeModal = useModal();
  const events = useTransferEvents(transfer.id);

  const downloadUrl = transfer.public_token
    ? `${window.location.origin}/t/${transfer.public_token}`
    : "";
  const isPublicLink = transfer.sharing_mode === "link";
  const totalSize = transfer.files.reduce((sum, f) => sum + f.size, 0);
  const days = daysUntil(transfer.expires_at);
  const isActive = transfer.status === "active";

  const copyLink = async () => {
    if (!downloadUrl) return;
    try {
      await navigator.clipboard.writeText(downloadUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API unavailable (insecure context) — silently swallow
    }
  };

  const handleDownload = (fileId: string) => {
    if (!transfer.public_token) return;
    downloadFile(transfer.public_token, fileId);
  };

  const handleRevokeDecision = (decision?: string | null) => {
    revokeModal.close();
    if (decision === "delete") {
      revokeTransfer.mutate(transfer.id);
    }
  };

  return (
    <div className="transfer-detail">
      <header className="transfer-detail__header">
        <h1 className="transfer-detail__title">
          {transfer.title || t("Untitled")}
        </h1>
        {transfer.status !== "active" && (
          <TransferStatusBadge status={transfer.status} />
        )}
      </header>

      <div className="transfer-detail__meta">
        {/* Both sharing modes expose a public token — the email flow is
            just a notified variant. Label stays "Public link" either way
            to match the recap mocks. */}
        <span className="transfer-detail__meta-item">
          <Globe />
          {t("Public link")}
        </span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>
          {isActive
            ? t("Expires in {{count}} days", { count: days })
            : t("Expired")}
        </span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>{t("{{count}} item", { count: transfer.files.length })}</span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>{formatFileSize(totalSize)}</span>
      </div>

      {isPublicLink && downloadUrl && (
        <div className="transfer-detail__link-box">
          <Input
            readOnly
            hideLabel
            label={t("Download link")}
            value={downloadUrl}
            variant="classic"
            fullWidth
            onFocus={(e) => e.currentTarget.select()}
          />
          {/* Link stays visible on deactivated transfers for reference,
              but copying is disabled — the URL no longer resolves. */}
          <Button
            color="neutral"
            variant="tertiary"
            icon={copied ? <Checkmark /> : <Copy />}
            onClick={copyLink}
            disabled={!isActive}
            aria-label={copied ? t("Link copied!") : t("Copy link")}
            title={copied ? t("Link copied!") : t("Copy link")}
          />
        </div>
      )}

      {!isPublicLink && transfer.recipients.length > 0 && (
        <section
          className={`transfer-detail__recipients-box${
            recipientsOpen ? " transfer-detail__recipients-box--open" : ""
          }`}
        >
          <button
            type="button"
            className="transfer-detail__recipients-toggle"
            onClick={() => setRecipientsOpen((o) => !o)}
            aria-expanded={recipientsOpen}
          >
            <span className="transfer-detail__recipients-chevron">
              <ChevronDown />
            </span>
            <span>
              {t("Recipients ({{count}})", {
                count: transfer.recipients.length,
              })}
            </span>
          </button>
          {recipientsOpen && (
            <ul className="transfer-detail__recipients-list">
              {transfer.recipients.map((r) => {
                const name = displayNameFromEmail(r.email);
                return (
                  <li key={r.id} className="transfer-detail__recipient-row">
                    <UserAvatar fullName={name} size="small" />
                    <span className="transfer-detail__recipient-name">
                      {name}
                    </span>
                    <span className="transfer-detail__recipient-email">
                      &lt;{r.email}&gt;
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      <ul
        className="transfer-detail__file-list"
        aria-label={t("Files ({{count}})", { count: transfer.files.length })}
      >
        {transfer.files.map((file) => (
          <FileItem
            key={file.id}
            icon={<Doc />}
            name={file.filename}
            size={formatFileSize(file.size)}
            state="done"
            action={
              <Button
                color="neutral"
                variant="tertiary"
                icon={<Download />}
                onClick={() => handleDownload(file.id)}
                disabled={!isActive || !transfer.public_token}
                aria-label={t("Download {{name}}", { name: file.filename })}
                title={t("Download")}
              />
            }
          />
        ))}
      </ul>

      {isActive && (
        <div className="transfer-detail__actions">
          {isPublicLink ? (
            <Button
              color="brand"
              icon={copied ? <Checkmark /> : <Copy />}
              onClick={copyLink}
            >
              {copied ? t("Link copied!") : t("Copy link")}
            </Button>
          ) : (
            // Email mode: triggers the backend resend task — re-emails the
            // shared HTML notification template to every recipient.
            <Button
              color="brand"
              icon={<ArrowUpRight />}
              onClick={() => resendTransfer.mutate(transfer.id)}
              disabled={
                transfer.recipients.length === 0 ||
                resendTransfer.isPending
              }
            >
              {resendTransfer.isPending
                ? t("Sending...")
                : resendTransfer.isSuccess
                  ? t("Sent!")
                  : t("Resend")}
            </Button>
          )}
          <Button
            color="error"
            variant="secondary"
            onClick={revokeModal.open}
            disabled={revokeTransfer.isPending}
          >
            {t("Deactivate")}
          </Button>
        </div>
      )}

      <section className="transfer-detail__history">
        <h2 className="transfer-detail__history-title">{t("History")}</h2>
        {events.isLoading ? (
          <Loader aria-label={t("Loading...")} />
        ) : !events.data || events.data.results.length === 0 ? (
          <p className="transfer-detail__history-empty">
            {t("No activity yet.")}
          </p>
        ) : (
          <div className="transfer-detail__history-table">
            <div className="transfer-detail__history-head">
              <div className="transfer-detail__history-col">
                {t("Activity")}
              </div>
              <div className="transfer-detail__history-col">
                <Clock />
                {t("Date")}
              </div>
              <div className="transfer-detail__history-col">
                <Perso />
                {t("By")}
              </div>
            </div>
            {events.data.results.map((ev) => {
              const label = t(EVENT_LABELS[ev.event_type] ?? ev.event_type);
              const by =
                ev.actor_type === "agent" ? t("You") : t("Recipient");
              return (
                <div key={ev.id} className="transfer-detail__history-row">
                  <div className="transfer-detail__history-activity">
                    <span
                      className="transfer-detail__history-tile"
                      aria-hidden="true"
                    >
                      <Folder />
                    </span>
                    <span>{label}</span>
                  </div>
                  <div className="transfer-detail__history-date">
                    {formatActivityDate(ev.created_at)}
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
