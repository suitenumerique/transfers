import { useTranslation } from "react-i18next";
import { Loader } from "@gouvfr-lasuite/cunningham-react";
import { useTransferEvents } from "../api/useTransferEvents";

const EVENT_LABELS: Record<string, string> = {
  transfer_created: "Transfer created",
  email_sent: "Notification email sent",
  link_opened: "Link opened",
  file_downloaded: "File downloaded",
  transfer_reactivated: "Transfer reactivated",
  transfer_revoked: "Transfer revoked",
  transfer_expired: "Transfer expired",
  files_deleted: "Files deleted",
};

export function TransferTimeline({ transferId }: { transferId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useTransferEvents(transferId);

  if (isLoading) return <Loader aria-label={t("Loading...")} />;
  if (!data || data.results.length === 0) return null;

  return (
    <section className="transfer-timeline">
      <h2>{t("Activity")}</h2>
      <ul className="transfer-timeline__list">
        {data.results.map((event) => {
          const date = new Date(event.created_at).toLocaleDateString("fr-FR", {
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          });
          const labelKey = EVENT_LABELS[event.event_type] ?? event.event_type;
          const label = t(labelKey);
          const detail =
            event.event_type === "file_downloaded" && event.payload?.filename
              ? ` — ${event.payload.filename}`
              : "";

          return (
            <li key={event.id} className="transfer-timeline__event">
              <span className="transfer-timeline__date">{date}</span>
              <span className="transfer-timeline__label">
                {label}
                {detail}
              </span>
              <span className="transfer-timeline__actor">
                {event.actor_type === "agent" ? t("You") : t("Recipient")}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
