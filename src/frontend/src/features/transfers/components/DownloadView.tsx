import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Input, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { Checkmark, CheckmarkShield, Copy, Doc, Download, Globe, WarningFilled } from "@gouvfr-lasuite/ui-kit/icons";
import type { DownloadTransferFull, ScanStatus } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { RelativeDate } from "@/features/ui/components/relative-date";
import { isExpired } from "@/features/utils/date";
import { downloadFile, downloadFileInIframe } from "../api/useDownload";
import { FileItem } from "./FileItem";

interface DownloadViewProps {
  transfer: DownloadTransferFull;
  token: string;
  isOwner?: boolean;
}

export function DownloadView({ transfer, token, isOwner = false }: DownloadViewProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const totalSize = transfer.files.reduce((a, f) => a + f.size, 0);
  const expired = isExpired(transfer.expires_at);
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
  // replace this entirely. Only clean files are eligible — pending / blocked
  // files are skipped rather than triggering a 202/403 from the backend.
  // "skipped" = scanning disabled on this instance: never scanned, no badge,
  // but downloadable just like "clean".
  const isDownloadable = (s: ScanStatus) => s === "clean" || s === "skipped";
  const downloadableFiles = transfer.files.filter((f) =>
    isDownloadable(f.scan_status),
  );
  const downloadAll = () => {
    downloadableFiles.forEach((file, i) => {
      setTimeout(() => downloadFileInIframe(token, file.id), i * 800);
    });
  };

  // Per-file antivirus badge shown after the size, plus whether the file is
  // releasable. Mirrors the backend's fail-closed gate: only "clean" is
  // downloadable; "pending" shows a live spinner (the query polls until it
  // resolves); "infected" / "error" are blocked.
  const scanBadge = (status: ScanStatus) => {
    switch (status) {
      case "skipped":
        return null;
      case "clean":
        return (
          <span
            className="file-item__scan file-item__scan--clean"
            title={t("Scanned — no virus found")}
          >
            <CheckmarkShield />
          </span>
        );
      case "pending":
        return (
          <span
            className="file-item__scan file-item__scan--pending"
            title={t("Antivirus scan in progress…")}
          >
            <Spinner />
            {t("Scanning…")}
          </span>
        );
      case "infected":
        return (
          <span
            className="file-item__scan file-item__scan--blocked"
            title={t("Blocked: a virus was detected in this file")}
          >
            <WarningFilled />
            {t("Virus detected")}
          </span>
        );
      default:
        return (
          <span
            className="file-item__scan file-item__scan--blocked"
            title={t("Blocked: the antivirus scan could not complete")}
          >
            <WarningFilled />
            {t("Scan failed")}
          </span>
        );
    }
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
          {expired ? t("Expired") : t("Expires")}{" "}
          <RelativeDate iso={transfer.expires_at} />
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
          {transfer.files.map((file) => {
            const downloadable = isDownloadable(file.scan_status);
            return (
              <FileItem
                key={file.id}
                icon={<Doc />}
                name={file.filename}
                size={formatFileSize(file.size)}
                state={
                  file.scan_status === "infected" ||
                  file.scan_status === "error"
                    ? "error"
                    : "done"
                }
                extras={scanBadge(file.scan_status)}
                action={
                  <Button
                    color="neutral"
                    variant="tertiary"
                    icon={<Download />}
                    disabled={!downloadable}
                    onClick={() => downloadFile(token, file.id)}
                    aria-label={t("Download {{name}}", { name: file.filename })}
                    title={
                      downloadable
                        ? t("Download")
                        : t("Available once the antivirus scan passes")
                    }
                  />
                }
              />
            );
          })}
        </ul>
      )}

      {downloadableFiles.length > 0 && (
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
