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
  unregisterE2eKey,
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
  // Every finalized transfer is encrypted; ``encryption_chunk_size`` is only
  // null for legacy plaintext transfers, which skip the SW decrypt path.
  const isEncrypted = transfer.encryption_chunk_size != null;
  // Snapshot the fragment once, at mount, before the effect below strips it
  // from the visible URL. Reading window.location.hash again after a rerun
  // (a new ``transfer.files`` reference is enough) would see it already
  // stripped and wrongly fall back to the paste screen.
  const keyFragmentRef = useRef<string>(
    typeof window !== "undefined"
      ? window.location.hash.replace(/^#/, "")
      : "",
  );
  // The key we hand the SW. Non-confidential transfers get it from the
  // backend (``encryption_key``); confidential transfers get it from the URL
  // fragment or, if that's missing, from the recipient pasting it.
  const autoKey = !transfer.confidential
    ? transfer.encryption_key || null
    : keyFragmentRef.current || null;

  // Decryption plumbing state: register the key with the SW before enabling
  // downloads. `ready` (go), `loading` (SW handshake), `need-key`
  // (confidential + no key yet, show the paste box), `error` (SW/registration
  // failed). Resolved synchronously here so the effect only does async work.
  type E2eState = "loading" | "ready" | "need-key" | "error";
  const [e2eState, setE2eState] = useState<E2eState>(() => {
    if (!isEncrypted) return "ready";
    if (typeof window === "undefined") return "loading";
    if (!autoKey) return "need-key";
    return "loading";
  });
  const [pastedKey, setPastedKey] = useState("");
  const [pasteError, setPasteError] = useState(false);
  // Tracks whether the SW currently holds this transfer's key, so the unmount
  // cleanup only unregisters when there's something to drop (set by both the
  // auto-effect and the paste handler).
  const registeredRef = useRef(false);
  // Monotonic id per auto-registration attempt. A stale attempt (its effect
  // cleaned up while its handshake was in flight) must not unregister a key a
  // newer attempt has since registered under the same token.
  const registerAttemptRef = useRef(0);

  const totalSize = transfer.files.reduce(
    (a, f) => a + (f.plaintext_size ?? f.size),
    0,
  );
  const expired = isExpired(transfer.expires_at);
  // Snapshot the original URL on first render, *before* the effect strips the
  // fragment. The "copy link" pill keeps this complete value so a forwarding
  // recipient still gets a working link, while the visible URL bar no longer
  // leaks the key.
  const initialUrlRef = useRef<string>(
    typeof window !== "undefined" ? window.location.href : "",
  );
  const downloadUrl = initialUrlRef.current;

  // Hand a key to the SW and flip to `ready`. Shared by the auto-effect
  // (backend key / URL fragment) and the paste box. A malformed key (wrong
  // length/base64) throws inside registerE2eKey → surfaces as an error the
  // caller maps to its state.
  const registerKey = async (keyStr: string): Promise<boolean> => {
    const chunkSize = transfer.encryption_chunk_size;
    if (!chunkSize) return false;
    const sw = await ensureE2eServiceWorker();
    if (!sw) return false;
    await registerE2eKey(sw, token, keyStr, transfer.files, chunkSize);
    registeredRef.current = true;
    return true;
  };

  useEffect(() => {
    if (!isEncrypted || !autoKey) return;
    // Confidential + fragment in URL: strip it from the visible URL (shoulder
    // surfing, history, copy-from-address-bar). The page keeps it in memory.
    // Non-confidential has no fragment to strip. Preserve the query string.
    if (transfer.confidential) {
      try {
        window.history.replaceState(
          null,
          "",
          window.location.pathname + window.location.search,
        );
      } catch {
        // replaceState can throw under exotic sandboxing; the URL stays as-is.
      }
    }
    const attempt = ++registerAttemptRef.current;
    let cancelled = false;
    (async () => {
      try {
        const ok = await registerKey(autoKey);
        if (cancelled) {
          // Cleanup already ran while the handshake was in flight — drop the
          // key we just registered so it doesn't linger in the SW. Skip if a
          // newer attempt superseded us: its key is the one now under this
          // token, and unregistering would break its decryption.
          if (ok && registerAttemptRef.current === attempt) {
            unregisterE2eKey(token);
          }
          return;
        }
        setE2eState(ok ? "ready" : "error");
      } catch {
        if (!cancelled) setE2eState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isEncrypted, autoKey, transfer.confidential, transfer.encryption_chunk_size, transfer.files, token]);

  // Drop the key from the SW registry on unmount (covers both the auto path
  // and a pasted key). The SW outlives the page and could be reused for
  // another transfer in the same tab, so stale keys are needless retention.
  useEffect(() => {
    return () => {
      if (registeredRef.current) unregisterE2eKey(token);
    };
  }, [token]);

  const submitPastedKey = async () => {
    const key = pastedKey.trim();
    if (!key) return;
    setPasteError(false);
    setE2eState("loading");
    try {
      const ok = await registerKey(key);
      setE2eState(ok ? "ready" : "need-key");
      if (!ok) setPasteError(true);
    } catch {
      // Malformed key (bad base64 / wrong length). A valid-length but wrong
      // key registers fine and instead fails at download time.
      setE2eState("need-key");
      setPasteError(true);
    }
  };

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
  // Encrypted and legacy-plaintext paths both go through an iframe rather
  // than an anchor click. For plaintext the reason is gesture throttling for
  // multi-file downloads. For encrypted the iframe also avoids a Firefox
  // race: an anchor click triggers a top-level navigation the SW sometimes
  // doesn't intercept on the first click; sub-frame requests don't hit that
  // path and the Content-Disposition header still triggers a download.
  const triggerDownload = (file: (typeof transfer.files)[number]) => {
    if (isEncrypted) {
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
        if (isEncrypted) {
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
        {transfer.confidential && (
          <>
            <span className="download-view__meta-sep">·</span>
            <Tooltip
              content={t(
                "Confidential transfer. Only your browser can decrypt it, using a key we never received.",
              )}
              placement="top"
            >
              <span className="download-view__meta-item download-view__meta-item--e2e">
                <Lock />
                {t("Confidential")}
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
                    {transfer.confidential && (
                      <Tooltip
                        content={t("Confidential file")}
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

      {isEncrypted && e2eState === "need-key" && (
        <div className="download-view__key-box">
          <Alert type={VariantType.INFO}>
            {t(
              "This transfer is confidential. Enter the decryption key the sender shared with you separately to unlock the files.",
            )}
          </Alert>
          <div className="download-view__key-input">
            <Input
              label={t("Decryption key")}
              value={pastedKey}
              onChange={(e) => {
                setPastedKey(e.currentTarget.value);
                setPasteError(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitPastedKey();
              }}
              variant="classic"
              fullWidth
              state={pasteError ? "error" : "default"}
              text={
                pasteError
                  ? t("That key didn't work. Check it and try again.")
                  : undefined
              }
            />
            <Button
              color="brand"
              onClick={() => void submitPastedKey()}
              disabled={!pastedKey.trim()}
            >
              {t("Unlock")}
            </Button>
          </div>
        </div>
      )}
      {isEncrypted && e2eState === "error" && (
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
