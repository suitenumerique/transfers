import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input } from "@gouvfr-lasuite/cunningham-react";
import { ArrowUpCircle, ArrowUpDown, Checkmark, Copy, Link as LinkIcon, MailCheckFilled } from "@gouvfr-lasuite/ui-kit/icons";
import type { TransferDetail } from "@/features/api/types";
import { RelativeDate } from "@/features/ui/components/relative-date";

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

  return (
    <div className="transfer-success" role="status">
      <div className="transfer-success__icon" aria-hidden="true">
        {isLink ? <LinkIcon /> : <MailCheckFilled />}
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
              size="small"
              color="neutral"
              variant="tertiary"
              icon={copied ? <Checkmark /> : <Copy />}
              onClick={handleCopy}
              aria-label={copied ? t("Link copied!") : t("Copy link")}
              title={copied ? t("Link copied!") : t("Copy link")}
            />
          </div>
          <p className="transfer-success__expiry">
            {t("This link expires")}{" "}
            <strong>
              <RelativeDate iso={transfer.expires_at} />
            </strong>
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
