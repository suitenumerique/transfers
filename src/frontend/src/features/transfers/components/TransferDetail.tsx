import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Input, Modal, ModalSize, useModal } from "@gouvfr-lasuite/cunningham-react";
import { Spinner, UserAvatar } from "@gouvfr-lasuite/ui-kit";
import { ArrowUpRight, Checkmark, ChevronDown, Clock, Copy, Doc, Download, Folder, Globe, Perso, Warning } from "@gouvfr-lasuite/ui-kit/icons";
import type { TransferDetail as TransferDetailType } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { downloadFile } from "../api/useDownload";
import { useResendTransfer } from "../api/useResendTransfer";
import { useDeactivateTransfer } from "../api/useDeactivateTransfer";
import { useTransferEvents } from "../api/useTransferEvents";
import { FileItem } from "./FileItem";
import { TransferStatusBadge } from "./TransferStatusBadge";

const EVENT_LABELS: Record<string, string> = {
  transfer_created: "Transfer created",
  email_sent: "Notification email sent",
  link_opened: "Link opened",
  file_downloaded: "File downloaded",
  transfer_deactivated_manually: "Transfer deactivated",
  transfer_deactivated_after_first_download: "Deactivated after download",
  transfer_deactivated_after_expiry: "Transfer expired",
  // file_deleted carries ``filename`` in its payload — interpolated below
  // so the row reads "Fichier screenshot.png supprimé" rather than a
  // generic label that forces the user to cross-reference the file list.
  file_deleted: "File {{filename}} deleted",
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

function daysBetween(startIso: string, endIso: string): number {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  return Math.max(0, Math.round(ms / (24 * 60 * 60 * 1000)));
}

export function TransferDetail({
  transfer,
}: {
  transfer: TransferDetailType;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const deactivateTransfer = useDeactivateTransfer();
  const resendTransfer = useResendTransfer();
  const [copied, setCopied] = useState(false);
  const [recipientsOpen, setRecipientsOpen] = useState(true);
  // True between hitting the resend endpoint and the recipient-invitation
  // task stamping ``notifications_completed_at`` again. Drives the button
  // spinner and triggers a poll of the transfer query so per-recipient
  // statuses refresh in place when the retry lands.
  const [isAwaitingRetry, setIsAwaitingRetry] = useState(false);
  // Snapshots the ``notifications_completed_at`` value at click time so
  // the completion effect waits for a *new* timestamp (not just non-null);
  // otherwise the still-cached previous timestamp would resolve the wait
  // before the task has even re-run.
  const seenCompletionRef = useRef<string | null>(null);
  const deactivateModal = useModal();
  const events = useTransferEvents(transfer.id);

  // Refresh the parent's useTransfer query every 2s while a retry is in
  // flight; the prop will update with the new recipient statuses.
  useEffect(() => {
    if (!isAwaitingRetry) return;
    const id = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ["transfers", transfer.id] });
    }, 2000);
    return () => clearInterval(id);
  }, [isAwaitingRetry, queryClient, transfer.id]);

  // Detect when the polled data shows the retry done.
  useEffect(() => {
    if (!isAwaitingRetry) return;
    const current = transfer.notifications_completed_at;
    if (current !== null && current !== seenCompletionRef.current) {
      setIsAwaitingRetry(false);
    }
  }, [transfer.notifications_completed_at, isAwaitingRetry]);

  const handleResend = () => {
    seenCompletionRef.current = transfer.notifications_completed_at;
    resendTransfer.mutate(transfer.id, {
      onSuccess: () => setIsAwaitingRetry(true),
    });
  };
  const isRetrying = resendTransfer.isPending || isAwaitingRetry;

  const downloadUrl = transfer.public_token
    ? `${window.location.origin}/t/${transfer.public_token}`
    : "";
  const isPublicLink = transfer.sharing_mode === "link";
  const totalSize = transfer.files.reduce((sum, f) => sum + f.size, 0);
  const isActive = transfer.status === "active";
  // Only recipients whose first send failed (or never happened) can be
  // retried — backend resend task filters on email_sent_at IS NULL.
  const hasPendingRecipients = transfer.recipients.some(
    (r) => r.email_sent_at === null,
  );

  // Meta summary: single line, single reason. For non-active transfers the
  // "why is it dead" signal replaces the raw expiry countdown (which is
  // noise once the transfer is terminal). The deactivation_reason column
  // on the server is the source of truth — we no longer infer it from a
  // mix of status + flags on the client.
  let metaReason: string;
  if (isActive) {
    metaReason = t("Expires in {{count}} days", { count: daysUntil(transfer.expires_at) });
  } else if (transfer.deactivation_reason === "expired") {
    metaReason = t("Expired after {{count}} days", {
      count: daysBetween(transfer.created_at, transfer.expires_at),
    });
  } else if (transfer.deactivation_reason === "first_download") {
    metaReason = t("Deactivated after download");
  } else if (transfer.deactivation_reason === "manual" || !transfer.deactivation_reason) {
    metaReason = t("Deactivated by you");
  } else {
    metaReason = t("Deactivated");
  }

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

  const handleDeactivateConfirm = () => {
    deactivateModal.close();
    deactivateTransfer.mutate(transfer.id);
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
        <span>{metaReason}</span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>{t("{{count}} file", { count: transfer.files.length })}</span>
        <span className="transfer-detail__meta-sep">·</span>
        <span>{formatFileSize(totalSize)}</span>
        {transfer.auto_archive_on_download && isActive && (
          <>
            <span className="transfer-detail__meta-sep">·</span>
            <span className="transfer-detail__meta-auto-archive">
              {t("Deactivates after download")}
            </span>
          </>
        )}
      </div>

      {downloadUrl && (
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
            size="small"
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
                const sent = r.email_sent_at !== null;
                return (
                  <li key={r.id} className="transfer-detail__recipient-row">
                    <UserAvatar fullName={name} size="small" />
                    <span className="transfer-detail__recipient-name">
                      {name}
                    </span>
                    <span className="transfer-detail__recipient-email">
                      &lt;{r.email}&gt;
                    </span>
                    <span
                      className={`transfer-detail__recipient-status${
                        sent
                          ? " transfer-detail__recipient-status--sent"
                          : " transfer-detail__recipient-status--failed"
                      }`}
                      title={sent ? t("Email sent") : t("Email not sent")}
                      aria-label={sent ? t("Email sent") : t("Email not sent")}
                    >
                      {sent ? <Checkmark /> : <Warning />}
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
          ) : hasPendingRecipients ? (
            // Email mode: retries the backend resend task, which only
            // re-emails recipients whose first send failed (email_sent_at
            // is NULL). Hidden entirely when nothing is pending — there's
            // nothing meaningful to do. The spinner stays on through the
            // POST + the polling window until the task stamps
            // ``notifications_completed_at`` again.
            <Button
              color="brand"
              icon={isRetrying ? <Spinner size="sm" /> : <ArrowUpRight />}
              onClick={handleResend}
              disabled={isRetrying}
            >
              {isRetrying ? t("Sending...") : t("Retry sending")}
            </Button>
          ) : null}
          <Button
            color="error"
            variant="secondary"
            onClick={deactivateModal.open}
            disabled={deactivateTransfer.isPending}
          >
            {t("Deactivate")}
          </Button>
        </div>
      )}

      <section className="transfer-detail__history">
        <h2 className="transfer-detail__history-title">{t("History")}</h2>
        {events.isLoading ? (
          <Spinner />
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
              const label = t(
                EVENT_LABELS[ev.event_type] ?? ev.event_type,
                ev.payload as Record<string, unknown>,
              );
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

      <Modal
        size={ModalSize.SMALL}
        isOpen={deactivateModal.isOpen}
        onClose={deactivateModal.close}
        title={t("Confirm deactivate")}
        rightActions={
          <>
            <Button
              color="neutral"
              variant="secondary"
              onClick={deactivateModal.close}
            >
              {t("Cancel")}
            </Button>
            <Button
              color="error"
              onClick={handleDeactivateConfirm}
              disabled={deactivateTransfer.isPending}
            >
              {t("Deactivate")}
            </Button>
          </>
        }
      >
        {t("This link will no longer work and files will be deleted.")}
      </Modal>
    </div>
  );
}
