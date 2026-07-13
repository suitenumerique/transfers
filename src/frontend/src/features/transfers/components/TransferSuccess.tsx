import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Tooltip } from "@gouvfr-lasuite/cunningham-react";
import { ArrowUpCircle, ArrowUpDown, Checkmark, CheckmarkShield, Copy, Link as LinkIcon, MailCheckFilled } from "@gouvfr-lasuite/ui-kit/icons";
import type { TransferDetail } from "@/features/api/types";
import { RelativeDate } from "@/features/ui/components/relative-date";
import { transferBaseUrl } from "../api/useDownload";

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
  // Confidential finalizes forward the fragment once from the form via the
  // navigation hash, then strip it from the visible URL — so it is present
  // for confidential transfers in both link and email mode. Null only when
  // the hash wasn't forwarded: non-E2E flows, or any render where the user
  // reached /confirm/<id> without it (refresh, bookmark).
  e2eFragment: string | null;
  onNewTransfer: () => void;
  onGoToDetail: () => void;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [keyCopied, setKeyCopied] = useState(false);

  // Confidential transfers embed the key in the shared link (link mode) or
  // hand it to the sender to pass out-of-band (email mode). Normal transfers
  // get a bare, reusable link — the backend serves the key to recipients.
  const baseUrl = transferBaseUrl(transfer.public_token);
  const downloadUrl =
    baseUrl && (!transfer.confidential || e2eFragment)
      ? transfer.confidential
        ? `${baseUrl}#${e2eFragment}`
        : baseUrl
      : "";

  const copyToClipboard = async (
    value: string,
    setFlag: (v: boolean) => void,
  ) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setFlag(true);
      setTimeout(() => setFlag(false), 2000);
    } catch {
      // Clipboard may be unavailable on insecure contexts; swallow silently.
    }
  };
  const handleCopy = () => copyToClipboard(downloadUrl, setCopied);
  const handleCopyKey = () =>
    copyToClipboard(e2eFragment ?? "", setKeyCopied);

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
              {transfer.confidential ? (
                <Tooltip
                  content={t(
                    "The key is embedded in this link and never reaches our servers. Anyone with the full link can read the files. Copy it now, we won't show it again.",
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
        <>
          <p className="transfer-success__body transfer-success__body--email">
            {t(
              "The download email has been sent successfully. Your recipients have",
            )}{" "}
            <strong>
              {t("{{count}} days", { count: daysUntil(transfer.expires_at) })}
            </strong>{" "}
            {t("to download your items.")}
          </p>
          {transfer.confidential && e2eFragment && (
            <div className="transfer-success__key-share">
              <p className="transfer-success__body">
                {t(
                  "This transfer is confidential: the email contains only the link. Send this decryption key to your recipients over a separate, trusted channel. We never received it and won't show it again.",
                )}
              </p>
              <div className="transfer-success__link-box">
                <Input
                  readOnly
                  hideLabel
                  label={t("Decryption key")}
                  value={e2eFragment}
                  variant="classic"
                  fullWidth
                  onFocus={(e) => e.currentTarget.select()}
                />
                <Button
                  type="button"
                  size="small"
                  color="neutral"
                  variant="tertiary"
                  icon={keyCopied ? <Checkmark /> : <Copy />}
                  onClick={handleCopyKey}
                  aria-label={keyCopied ? t("Key copied!") : t("Copy key")}
                  title={keyCopied ? t("Key copied!") : t("Copy key")}
                />
              </div>
            </div>
          )}
          {transfer.confidential && !e2eFragment && (
            <p className="transfer-success__body">
              {t(
                "The decryption key isn't available on this device and can't be recovered. If you didn't copy it when you created the transfer, your recipients won't be able to open the files.",
              )}
            </p>
          )}
        </>
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
