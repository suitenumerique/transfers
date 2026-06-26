import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Input, Tooltip, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { Checkmark, CheckmarkShield, Copy, Doc, Download, Globe, Lock, Warning } from "@gouvfr-lasuite/ui-kit/icons";
import type { DownloadTransferFull, ScanStatus } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { RelativeDate } from "@/features/ui/components/relative-date";
import { isExpired } from "@/features/utils/date";
import { downloadFile, downloadFileInIframe } from "../api/useDownload";
import {
  ensureE2eServiceWorker,
  registerE2eKey,
  streamingDownloadUrl,
} from "../upload/e2eServiceWorker";
import { FileItem } from "./FileItem";

interface DownloadViewProps {
  transfer: DownloadTransferFull;
  token: string;
  isOwner?: boolean;
}

export function DownloadView({ transfer, token, isOwner = false }: DownloadViewProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  // E2E plumbing state: extract the key from the URL fragment and register
  // it with the decryption SW before enabling the download buttons. Four
  // outcomes: `ready` (good to go), `loading` (SW handshake in flight),
  // `no-key` (fragment missing — wrong link), or `error` (chunk size
  // missing on the transfer, or SW registration failed). The sync
  // checks resolve at initial-state time so the effect only handles
  // the async SW registration, never a synchronous setState.
  type E2eState = "loading" | "ready" | "no-key" | "error";
  const [e2eState, setE2eState] = useState<E2eState>(() => {
    if (!transfer.e2e_encrypted) return "ready";
    if (typeof window === "undefined") return "loading";
    const fragment = window.location.hash.replace(/^#/, "");
    if (!fragment) return "no-key";
    if (!transfer.encryption_chunk_size) return "error";
    return "loading";
  });

  const totalSize = transfer.files.reduce(
    (a, f) => a + (f.plaintext_size ?? f.size),
    0,
  );
  const expired = isExpired(transfer.expires_at);
  // Snapshot the original URL on first render, *before* the E2E effect
  // strips the fragment from the address bar. The "copy link" pill keeps
  // this complete value so a forwarding recipient still gets a working
  // link, while the visible URL bar no longer leaks the key.
  const initialUrlRef = useRef<string>(
    typeof window !== "undefined" ? window.location.href : "",
  );
  const downloadUrl = initialUrlRef.current;

  useEffect(() => {
    if (!transfer.e2e_encrypted) return;
    const fragment = window.location.hash.replace(/^#/, "");
    const chunkSize = transfer.encryption_chunk_size;
    // The initial-state initializer already mapped a missing fragment to
    // "no-key" and a missing chunk size to "error"; bail before touching
    // history or the SW.
    if (!fragment || !chunkSize) return;
    // Remove the key from the visible URL: shoulder-surfing, browser
    // history, copy-from-address-bar all stop leaking it. The page keeps
    // the fragment in-memory (passed to the SW below) so downloads still
    // work — the only thing the user loses by stripping is the ability to
    // recover the key by refreshing the tab.
    try {
      window.history.replaceState(null, "", window.location.pathname);
    } catch {
      // replaceState can throw under exotic sandboxing (about:blank parents,
      // some embedded webviews); the visible URL stays as-is, which is a
      // degradation but not a blocker for downloading.
    }
    let cancelled = false;
    (async () => {
      try {
        const sw = await ensureE2eServiceWorker();
        if (!sw) {
          if (!cancelled) setE2eState("error");
          return;
        }
        await registerE2eKey(sw, token, fragment, transfer.files, chunkSize);
        if (!cancelled) setE2eState("ready");
      } catch {
        if (!cancelled) setE2eState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [transfer.e2e_encrypted, transfer.encryption_chunk_size, transfer.files, token]);

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
  const isDownloadable = (s: ScanStatus) =>
    s === "clean" || s === "skipped" || s === "too_large";
  const downloadableFiles = transfer.files.filter((f) =>
    isDownloadable(f.scan_status),
  );
  // E2E and non-E2E paths both go through an iframe rather than an
  // anchor click. For non-E2E the existing reason still holds (gesture
  // throttling for multi-file downloads). For E2E the iframe avoids a
  // Firefox-specific race: an anchor click triggers a top-level
  // navigation, which the SW occasionally doesn't intercept on the very
  // first click after registration. Sub-frame requests don't hit that
  // path and the Content-Disposition header still triggers a download.
  const triggerDownload = (file: (typeof transfer.files)[number]) => {
    if (transfer.e2e_encrypted) {
      const iframe = document.createElement("iframe");
      iframe.style.display = "none";
      iframe.src = streamingDownloadUrl(token, file.id, file.filename);
      document.body.appendChild(iframe);
      setTimeout(() => iframe.remove(), 5000);
    } else {
      downloadFile(token, file.id);
    }
  };
  const downloadAll = () => {
    downloadableFiles.forEach((file, i) => {
      setTimeout(() => {
        if (transfer.e2e_encrypted) {
          triggerDownload(file);
        } else {
          downloadFileInIframe(token, file.id);
        }
      }, i * 800);
    });
  };

  // Recipients only ever see transfers whose files are all clean — the scan is
  // a hard gate at creation, so infected/pending never reach here. "skipped"
  // (scanning disabled on the instance) shows no badge.
  const scanBadge = (status: ScanStatus) => {
    if (status === "clean") {
      return (
        <Tooltip content={t("Scanned, no virus found")} placement="top">
          <span className="file-item__scan file-item__scan--clean">
            <CheckmarkShield />
          </span>
        </Tooltip>
      );
    }
    if (status === "too_large") {
      return (
        <Tooltip
          content={t(
            "This file was not scanned for viruses because it is too large.",
          )}
          placement="top"
        >
          <span className="file-item__scan file-item__scan--warning">
            <Warning />
          </span>
        </Tooltip>
      );
    }
    return null;
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
        {transfer.e2e_encrypted && (
          <>
            <span className="download-view__meta-sep">·</span>
            <Tooltip
              content={t(
                "Your browser holds the decryption key (from the link). We only see encrypted content.",
              )}
              placement="top"
            >
              <span className="download-view__meta-item download-view__meta-item--e2e">
                <Lock />
                {t("End-to-end encrypted")}
              </span>
            </Tooltip>
          </>
        )}
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
                size={formatFileSize(file.plaintext_size ?? file.size)}
                state={
                  file.scan_status === "infected" ||
                  file.scan_status === "error"
                    ? "error"
                    : "done"
                }
                extras={
                  <>
                    {transfer.e2e_encrypted && (
                      <Tooltip
                        content={t("End-to-end encrypted file")}
                        placement="top"
                      >
                        <span className="file-item__scan file-item__scan--encrypted">
                          <Lock />
                        </span>
                      </Tooltip>
                    )}
                    {scanBadge(file.scan_status)}
                  </>
                }
                action={
                  <Button
                    color="neutral"
                    variant="tertiary"
                    icon={<Download />}
                    disabled={!downloadable || e2eState !== "ready"}
                    onClick={() => triggerDownload(file)}
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

      {transfer.e2e_encrypted && e2eState === "no-key" && (
        <Alert type={VariantType.ERROR}>
          {t(
            "The decryption key is missing from this link. Make sure you opened the original link in full.",
          )}
        </Alert>
      )}
      {transfer.e2e_encrypted && e2eState === "error" && (
        <Alert type={VariantType.ERROR}>
          {t(
            "We couldn't set up the decryption helper in your browser. Try a different browser or check that service workers are enabled.",
          )}
        </Alert>
      )}

      {downloadableFiles.length > 0 && (
        <Button
          color="brand"
          icon={<Download />}
          fullWidth
          onClick={downloadAll}
          disabled={e2eState !== "ready"}
          className="download-view__download-all"
        >
          {t("Download all")}
        </Button>
      )}
    </div>
  );
}
