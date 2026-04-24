import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input } from "@gouvfr-lasuite/cunningham-react";
import {
  ArrowUpCircle,
  ArrowUpDown,
  Checkmark,
  Copy,
  MailCheckFilled,
} from "@gouvfr-lasuite/ui-kit";
import type { TransferDetail } from "@/features/api/types";

function formatExpiry(iso: string): string {
  // Matches the Figma mock: "25/12/2026 à 00h00". We split on `|` so the
  // date and time chunks can be wrapped in <strong> separately.
  const d = new Date(iso);
  const date = d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  const time = d
    .toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
    .replace(":", "h");
  return `${date}|${time}`;
}

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(1, Math.round(ms / (24 * 60 * 60 * 1000)));
}

export function TransferSuccess({
  transfer,
  onNewTransfer,
  onGoToDetail,
}: {
  transfer: TransferDetail;
  onNewTransfer: () => void;
  onGoToDetail: () => void;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const downloadUrl = transfer.public_token
    ? `${window.location.origin}/t/${transfer.public_token}`
    : "";

  const handleCopy = async () => {
    if (!downloadUrl) return;
    try {
      await navigator.clipboard.writeText(downloadUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be unavailable on insecure contexts; swallow silently.
    }
  };

  const isLink = transfer.sharing_mode === "link";
  const [expiryDate, expiryTime] = formatExpiry(transfer.expires_at).split("|");

  return (
    <div className="transfer-success" role="status">
      <div className="transfer-success__icon" aria-hidden="true">
        <MailCheckFilled />
      </div>
      <h1 className="transfer-success__title">
        {isLink ? t("Transfer ready") : t("Transfer sent")}
      </h1>
      {isLink ? (
        <>
          <p className="transfer-success__body">
            {t("Download link to share:")}
          </p>
          <div className="transfer-success__link-box">
            <Input
              readOnly
              hideLabel
              label={t("Download link")}
              value={downloadUrl}
              variant="classic"
              fullWidth
              onFocus={(e) => e.currentTarget.select()}
            />
            <Button
              type="button"
              color="neutral"
              variant="tertiary"
              icon={copied ? <Checkmark /> : <Copy />}
              onClick={handleCopy}
              aria-label={copied ? t("Link copied!") : t("Copy link")}
              title={copied ? t("Link copied!") : t("Copy link")}
            />
          </div>
          <p className="transfer-success__expiry">
            {t("This link will expire on")} <strong>{expiryDate}</strong>{" "}
            {t("at")} <strong>{expiryTime}</strong>
          </p>
        </>
      ) : (
        <p className="transfer-success__body transfer-success__body--email">
          {t(
            "The download email has been sent successfully. Your recipients have",
          )}{" "}
          <strong>
            {t("{{count}} days", { count: daysUntil(transfer.expires_at) })}
          </strong>{" "}
          {t("to download your items.")}
        </p>
      )}

      <div className="transfer-success__actions">
        <Button
          color="neutral"
          variant="tertiary"
          icon={<ArrowUpDown />}
          onClick={onNewTransfer}
        >
          {t("Start new transfer")}
        </Button>
        <Button color="brand" icon={<ArrowUpCircle />} onClick={onGoToDetail}>
          {t("View summary")}
        </Button>
      </div>
    </div>
  );
}
