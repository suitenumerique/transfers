import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Tooltip } from "@gouvfr-lasuite/cunningham-react";
import { ArrowUpCircle, ArrowUpDown, Checkmark, CheckmarkShield, Copy, Link as LinkIcon, MailCheckFilled } from "@gouvfr-lasuite/ui-kit/icons";
import type { TransferDetail } from "@/features/api/types";
import { RelativeDate } from "@/features/ui/components/relative-date";

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(1, Math.round(ms / (24 * 60 * 60 * 1000)));
}

export function TransferSuccess({
  transfer,
  e2eFragment,
  onNewTransfer,
  onGoToDetail,
}: {
  transfer: TransferDetail;
  // For E2E link-mode finalizes only: the fragment is forwarded once from
  // the form via navigation hash and stripped from the visible URL. Null
  // for non-E2E, for email mode, and for any re-render where the user
  // arrived at /confirm/<id> without the fragment (refresh, bookmark).
  e2eFragment: string | null;
  onNewTransfer: () => void;
  onGoToDetail: () => void;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const baseUrl = transfer.public_token
    ? `${window.location.origin}/t/${transfer.public_token}`
    : "";
  const downloadUrl =
    baseUrl && (!transfer.e2e_encrypted || e2eFragment)
      ? transfer.e2e_encrypted
        ? `${baseUrl}#${e2eFragment}`
        : baseUrl
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
  // Only true when *every* file was actually scanned clean — not the "skipped"
  // state of an AV-disabled instance, nor a "too_large" file that bypassed the
  // scan. Reassures the sender the whole transfer passed the virus check before
  // going out, so we don't over-claim on a mixed clean / not-scanned list.
  const scanned =
    transfer.files.length > 0 &&
    transfer.files.every((f) => f.scan_status === "clean");

  return (
    <div className="transfer-success" role="status">
      <div className="transfer-success__icon" aria-hidden="true">
        {isLink ? <LinkIcon /> : <MailCheckFilled />}
      </div>
      <h1 className="transfer-success__title">
        {isLink ? t("Transfer ready") : t("Transfer sent")}
      </h1>
      {scanned && (
        <p className="transfer-success__scan">
          <CheckmarkShield />
          {t("Files scanned, no virus found")}
        </p>
      )}
      {isLink ? (
        downloadUrl ? (
          <>
            <p className="transfer-success__body">
              {transfer.e2e_encrypted ? (
                <Tooltip
                  content={t(
                    "Encryption happens in your browser. The key is embedded in this link and never reaches our servers. Anyone with the link can read the files.",
                  )}
                  placement="top"
                >
                  <span className="transfer-success__e2e-tip">
                    {t(
                      "Link to share. Copy it now, we won't show it again:",
                    )}
                  </span>
                </Tooltip>
              ) : (
                t("Download link to share:")
              )}
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
          <p className="transfer-success__body">
            {t(
              "This link is not available on this device. Use the copy you saved when you created the transfer.",
            )}
          </p>
        )
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
