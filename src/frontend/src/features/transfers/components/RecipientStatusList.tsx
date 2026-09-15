import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Tooltip } from "@gouvfr-lasuite/cunningham-react";
import { UserAvatar } from "@gouvfr-lasuite/ui-kit";
import { CircleCheckFilled, Eye, Loader, Mail, Warning } from "@gouvfr-lasuite/ui-kit/icons";
import type { TransferDetail, TransferRecipient } from "@/features/api/types";
import { RelativeDate } from "@/features/ui/components/relative-date";

// While the invitation task is running, statuses flip from "sending" within
// seconds — poll fast. Afterwards "opened" / "downloaded" trickle in over
// hours; a slow tick keeps the page honest without hammering the API.
const SENDING_POLL_MS = 2_000;
const ACTIVITY_POLL_MS = 15_000;

export function displayNameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  if (!local) return email;
  const parts = local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1));
  return parts.length >= 2 ? parts.join(" ") : email;
}

export function useRecipientStatusPolling(transfer: TransferDetail) {
  const queryClient = useQueryClient();
  const sending = transfer.notifications_completed_at === null;
  const fileCount = transfer.files.length;
  const everyoneDone =
    fileCount > 0 &&
    transfer.recipients.every((r) => r.downloaded_file_count >= fileCount);
  const active =
    transfer.recipients.length > 0 &&
    transfer.status === "active" &&
    (sending || !everyoneDone);

  useEffect(() => {
    if (!active) return;
    const tick = () => {
      // A backgrounded tab doesn't need fresh icons; resume on focus.
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ["transfers", transfer.id] });
    };
    const id = setInterval(tick, sending ? SENDING_POLL_MS : ACTIVITY_POLL_MS);
    return () => clearInterval(id);
  }, [active, sending, queryClient, transfer.id]);
}

function StatusCell({
  recipient,
  fileCount,
}: {
  recipient: TransferRecipient;
  fileCount: number;
}) {
  const { t } = useTranslation();
  let icon: React.ReactNode;
  let label: string;
  let when: string | null = null;
  switch (recipient.status) {
    case "sending":
      icon = <Loader />;
      label = t("Sending");
      break;
    case "failed":
      icon = <Warning />;
      label = t("Not sent");
      break;
    case "sent":
      icon = <Mail />;
      label = t("Sent");
      when = recipient.email_sent_at;
      break;
    case "opened":
      icon = <Eye />;
      label = t("Opened");
      when = recipient.opened_at;
      break;
    case "downloaded":
      icon = <CircleCheckFilled />;
      label =
        recipient.downloaded_file_count >= fileCount
          ? t("Downloaded")
          : t("Downloaded {{n}} of {{total}} files", {
              n: recipient.downloaded_file_count,
              total: fileCount,
            });
      when = recipient.downloaded_at;
      break;
  }
  const cell = (
    <span
      className={`recipient-status__state recipient-status__state--${recipient.status}`}
      aria-label={label}
    >
      {icon}
      <span className="recipient-status__label">{label}</span>
    </span>
  );
  if (!when) return cell;
  return (
    <Tooltip
      content={
        <>
          {label} · <RelativeDate iso={when} />
        </>
      }
      placement="top"
    >
      {cell}
    </Tooltip>
  );
}

// One row per recipient with its delivery / activity state. Used on the
// post-send summary (where it replaces the old "wait for the emails" spinner
// page) and on the transfer page. Polls the transfer query itself while
// anything can still change.
export function RecipientStatusList({
  transfer,
  className,
}: {
  transfer: TransferDetail;
  className?: string;
}) {
  useRecipientStatusPolling(transfer);
  const fileCount = transfer.files.length;
  return (
    <ul className={`recipient-status${className ? ` ${className}` : ""}`}>
      {transfer.recipients.map((r) => {
        const name = displayNameFromEmail(r.email);
        return (
          <li key={r.id} className="recipient-status__row">
            <UserAvatar fullName={name} size="small" />
            <span className="recipient-status__name">{name}</span>
            <span className="recipient-status__email">&lt;{r.email}&gt;</span>
            <StatusCell recipient={r} fileCount={fileCount} />
          </li>
        );
      })}
    </ul>
  );
}
