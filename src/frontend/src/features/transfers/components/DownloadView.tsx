import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Input, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { Checkmark, Copy, Doc, Download, Globe } from "@gouvfr-lasuite/ui-kit/icons";
import type { DownloadTransferFull } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { downloadFile, downloadFileInIframe } from "../api/useDownload";
import { FileItem } from "./FileItem";

interface DownloadViewProps {
  transfer: DownloadTransferFull;
  token: string;
  isOwner?: boolean;
}

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(0, Math.ceil(ms / (24 * 60 * 60 * 1000)));
}

export function DownloadView({ transfer, token, isOwner = false }: DownloadViewProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const totalSize = transfer.files.reduce((a, f) => a + f.size, 0);
  const days = daysUntil(transfer.expires_at);
  const downloadUrl =
    typeof window !== "undefined" ? window.location.href : "";

  const copyLink = async () => {
    if (!downloadUrl) return;
    try {
      await navigator.clipboard.writeText(downloadUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable on insecure contexts — silent
    }
  };

  // "Tout télécharger" — there's no server-side zip endpoint yet, so we
  // fan out one presigned download per file. Iframes (rather than anchor
  // clicks) sidestep the browser's user-gesture throttling that silently
  // drops the 2nd+ download when several fire in close succession. The
  // 800ms stagger still leaves time for the "allow multiple downloads"
  // prompt the first time it appears. A real bulk-zip endpoint would
  // replace this entirely.
  const downloadAll = () => {
    transfer.files.forEach((file, i) => {
      setTimeout(() => downloadFileInIframe(token, file.id), i * 800);
    });
  };

  return (
    <div className="download-view">
      <h1 className="download-view__title">
        {transfer.title || t("Transfer")}
      </h1>

      <div className="download-view__meta">
        <span className="download-view__meta-item">
          <Globe />
          {t("Public link")}
        </span>
        <span className="download-view__meta-sep">·</span>
        <span>
          {days > 0
            ? t("Expires in {{count}} days", { count: days })
            : t("Expired")}
        </span>
        <span className="download-view__meta-sep">·</span>
        <span>{t("{{count}} file", { count: transfer.files.length })}</span>
        <span className="download-view__meta-sep">·</span>
        <span>{formatFileSize(totalSize)}</span>
      </div>

      <hr className="download-view__divider" />

      {transfer.auto_archive_on_download && (
        <Alert
          type={VariantType.WARNING}
          className="download-view__auto-archive-alert"
        >
          {isOwner
            ? t("Single-use link. Deactivates after full download by another user.")
            : t("Single-use link. Deactivates after full download.")}
        </Alert>
      )}

      {/* Email-mode transfers reach the recipient via the notification
          email itself — re-surfacing the URL here invites accidental
          forwarding (the link is single-channel by design). Keep the
          copy pill only for "link" mode. */}
      {downloadUrl && transfer.sharing_mode === "link" && (
        <div className="download-view__link-box">
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
            size="small"
            color="neutral"
            variant="tertiary"
            icon={copied ? <Checkmark /> : <Copy />}
            onClick={copyLink}
            aria-label={copied ? t("Link copied!") : t("Copy link")}
            title={copied ? t("Link copied!") : t("Copy link")}
          />
        </div>
      )}

      {transfer.files.length > 0 && (
        <ul
          className="download-view__file-list"
          aria-label={t("Files ({{count}})", {
            count: transfer.files.length,
          })}
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
                  onClick={() => downloadFile(token, file.id)}
                  aria-label={t("Download {{name}}", { name: file.filename })}
                  title={t("Download")}
                />
              }
            />
          ))}
        </ul>
      )}

      {transfer.files.length > 0 && (
        <Button
          color="brand"
          icon={<Download />}
          fullWidth
          onClick={downloadAll}
          className="download-view__download-all"
        >
          {t("Download all")}
        </Button>
      )}
    </div>
  );
}
