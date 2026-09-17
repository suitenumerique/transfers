import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Input, Tooltip, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { Checkmark, CheckmarkShield, Copy, Doc, Download, Globe, Lock, Warning } from "@gouvfr-lasuite/ui-kit/icons";
import type { DownloadTransferFull, ScanStatus } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { RelativeDate } from "@/features/ui/components/relative-date";
import { downloadFile, downloadFileInIframe } from "../api/useDownload";
import {
  ensureEncryptionServiceWorker,
  onDownloadNotice,
  registerEncryptionKey,
  startServiceWorkerKeepalive,
  streamingDownloadUrl,
  unregisterEncryptionKey,
} from "../upload/encryptionServiceWorker";
import { hasUnscannedFiles } from "../utils/scanStatus";
import { useDeadlineFlag } from "../utils/useDeadlineFlag";
import { ButtonSpinner } from "./ButtonSpinner";
import { FileItem } from "./FileItem";

// Firefox's download manager re-requests a paused or retried download
// outside any page (never through the Service Worker); see interruptedIds.
const IS_FIREFOX =
  typeof navigator !== "undefined" && /\bFirefox\//.test(navigator.userAgent);

// The "copy link" pill hands the recipient a link to forward. Drop the
// personal ``?r=`` first: a forwarded link would otherwise attribute the
// next person's downloads to the original recipient. The fragment (key)
// survives untouched.
function stripRecipientToken(href: string): string {
  try {
    const u = new URL(href);
    u.searchParams.delete("r");
    return u.toString();
  } catch {
    return href;
  }
}

interface DownloadViewProps {
  transfer: DownloadTransferFull;
  token: string;
  // Recipient attribution token from the emailed link (``?r=``); forwarded
  // on every download call so the sender sees who opened / downloaded.
  recipientToken?: string;
  isOwner?: boolean;
}


export function DownloadView({
  transfer,
  token,
  recipientToken,
  isOwner = false,
}: DownloadViewProps) {
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
  type EncryptionState = "loading" | "ready" | "need-key" | "error";
  const [encryptionState, setEncryptionState] = useState<EncryptionState>(() => {
    if (!isEncrypted) return "ready";
    if (typeof window === "undefined") return "loading";
    if (!autoKey) return "need-key";
    return "loading";
  });
  const [pastedKey, setPastedKey] = useState("");
  const [pasteError, setPasteError] = useState(false);
  // Files clicked whose first decrypted bytes haven't left the SW yet. The
  // browser shows nothing until they do (a whole ciphertext chunk has to
  // be fetched and authenticated first — on Firefox the download UI only
  // appears at that point), so the button spins in the meantime. Cleared
  // by the SW's notice; the hidden iframe that carries the request is
  // dropped a moment later, once the download manager owns the stream.
  // No timer: removing the iframe before the first byte aborts the
  // request, which on a slow link is exactly when a 25 MiB first chunk
  // is still downloading.
  // Keyed by a per-click request id (also in the iframe URL), so a notice
  // from the SW is matched to this click only — never to another tab's or
  // an earlier click's download of the same file.
  const [pending, setPending] = useState<Map<string, string>>(() => new Map());
  const iframesRef = useRef<Map<string, HTMLIFrameElement>>(new Map());
  // Every request id this page issued (→ file id), kept after the iframe
  // is gone: the SW's "interrupted" notice comes minutes later, when the
  // recipient pauses or cancels from the browser's download manager.
  const requestsRef = useRef<Map<string, string>>(new Map());
  // Files whose download the browser interrupted (paused or cancelled
  // from its download manager). The next click on such a file is sent as
  // a resume, which a one-shot transfer needs to hand the file out again.
  // Only surfaced on Firefox: its Resume/Retry re-request the URL outside
  // any page, which no Service Worker sees, so the recipient has to
  // restart from here (docs/ENCRYPTION.md, "Interrupted downloads").
  // Chrome resumes through the worker on its own.
  const interruptedRef = useRef<Set<string>>(new Set());
  const [interruptedIds, setInterruptedIds] = useState<Set<string>>(
    () => new Set(),
  );
  const preparingIds = new Set(pending.values());
  const settle = (requestId: string) =>
    setPending((prev) => {
      if (!prev.has(requestId)) return prev;
      const next = new Map(prev);
      next.delete(requestId);
      return next;
    });
  const dropIframe = (requestId: string) => {
    const iframe = iframesRef.current.get(requestId);
    if (!iframe) return;
    iframesRef.current.delete(requestId);
    iframe.remove();
  };
  useEffect(
    () =>
      onDownloadNotice((notice) => {
        const fileId = requestsRef.current.get(notice.requestId);
        if (!fileId) return; // not ours
        if (notice.kind === "interrupted") {
          // Also reached before any byte went out (the download cancelled
          // while "preparing"): nothing will stream, so settle the click
          // here too.
          settle(notice.requestId);
          dropIframe(notice.requestId);
          interruptedRef.current.add(fileId);
          if (IS_FIREFOX) {
            setInterruptedIds((prev) => new Set(prev).add(fileId));
          }
          return;
        }
        settle(notice.requestId);
        if (notice.kind === "failed") {
          dropIframe(notice.requestId);
        } else {
          setTimeout(() => dropIframe(notice.requestId), 5_000);
        }
      }),
    [],
  );
  // Clicks belong to the transfer they were made on: drop them (and
  // their iframes) when the token changes in place, or on unmount.
  useEffect(() => {
    const iframes = iframesRef.current;
    const requests = requestsRef.current;
    const interrupted = interruptedRef.current;
    return () => {
      for (const iframe of iframes.values()) iframe.remove();
      iframes.clear();
      requests.clear();
      interrupted.clear();
      setPending(new Map());
      setInterruptedIds(new Set());
    };
  }, [token]);
  // Tracks whether the SW currently holds this transfer's key, so the unmount
  // cleanup only unregisters when there's something to drop (set by both the
  // auto-effect and the paste handler).
  const registeredRef = useRef(false);
  // A stale attempt (cleaned up mid-handshake) must not unregister the key a
  // newer one has since registered under the same token.
  const registerAttemptRef = useRef(0);
  // Flipped to false in the unmount cleanup below so async paste handlers can
  // tell "still on the page" from "resolved after the user navigated away".
  const mountedRef = useRef(true);

  const totalSize = transfer.files.reduce(
    (a, f) => a + (f.plaintext_size ?? f.size),
    0,
  );
  const expired = useDeadlineFlag(transfer.expires_at);
  // Snapshot the original URL on first render, *before* the effect strips the
  // fragment. The "copy link" pill keeps this complete value so a forwarding
  // recipient still gets a working link, while the visible URL bar no longer
  // leaks the key.
  const initialUrlRef = useRef<string>(
    typeof window !== "undefined" ? stripRecipientToken(window.location.href) : "",
  );
  const downloadUrl = initialUrlRef.current;

  // The raw key string that's currently registered with the SW. Kept in a
  // ref (not state) so it survives re-renders without causing them, and so
  // ``triggerDownload`` can re-register it synchronously right before a
  // download click without waiting for a state update to flush. Cleared on
  // unmount. Populated by ``registerKey`` for both the auto path and the
  // paste path — the paste input can be cleared safely once this is set.
  const activeKeyRef = useRef<string | null>(null);
  // Hand a key to the SW and flip to `ready`. Shared by the auto-effect
  // (backend key / URL fragment) and the paste box. A malformed key (wrong
  // length/base64) throws inside registerEncryptionKey → surfaces as an error the
  // caller maps to its state.
  const registerKey = async (keyStr: string): Promise<boolean> => {
    const chunkSize = transfer.encryption_chunk_size;
    if (!chunkSize) return false;
    const sw = await ensureEncryptionServiceWorker();
    if (!sw) return false;
    await registerEncryptionKey(
      sw,
      token,
      keyStr,
      transfer.files,
      chunkSize,
      transfer.expires_at,
    );
    if (!mountedRef.current) {
      // Resolved after the unmount cleanup already cleared these refs. Don't
      // resurrect them — the caller decides whether to drop the key SW-side.
      return true;
    }
    activeKeyRef.current = keyStr;
    registeredRef.current = true;
    return true;
  };

  // Belt-and-suspenders against the keepalive missing a tick (mobile tab
  // suspend, background-throttled setInterval, a browser that killed the
  // SW despite the pings): re-register the same key right before every
  // download click. Idempotent — the SW's ``REGISTRY.set`` overwrites,
  // handshake is a ~10ms postMessage round-trip when the worker is alive,
  // and a click that would otherwise 500 with "Decryption key not loaded"
  // now spins the worker back up + reloads the key transparently. Returns
  // ``false`` when we've got nothing to re-register (should never happen
  // once ``encryptionState === "ready"``, defensive nonetheless).
  const refreshEncryptionKey = async (): Promise<boolean> => {
    const keyStr = activeKeyRef.current;
    if (!keyStr) return false;
    try {
      return await registerKey(keyStr);
    } catch {
      return false;
    }
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
          // key we just registered so it doesn't linger in the SW. While
          // still mounted, skip if a newer attempt superseded us: its key is
          // the one now under this token, and unregistering would break its
          // decryption. After unmount nobody owns the token any more, so
          // every successful registration gets dropped — a later attempt
          // may have failed (ack timeout) and left ours as the survivor.
          if (
            ok &&
            (!mountedRef.current || registerAttemptRef.current === attempt)
          ) {
            unregisterEncryptionKey(token);
          }
          return;
        }
        setEncryptionState(ok ? "ready" : "error");
      } catch {
        if (!cancelled) setEncryptionState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isEncrypted, autoKey, transfer.confidential, transfer.encryption_chunk_size, transfer.files, token]);

  // Unmount-only. Deliberately not in the [token] effect below: that
  // cleanup also runs on an in-place token change (SPA navigation from one
  // /t/… link to another reuses this instance), and a false ``mountedRef``
  // would then turn every later paste and download click into a silent
  // no-op for the rest of the instance's life.
  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Drop the key from the SW (its in-memory registry and its IndexedDB
  // copy) when the token goes away (unmount, or in-place token change).
  // Covers both the auto path and a pasted key. Also clear the page's
  // in-memory copy: keeping it around after the page is gone would let a
  // stray ``triggerDownload`` (from a lingering handler on a detached DOM
  // node, etc.) re-register a key the user was done with.
  useEffect(() => {
    return () => {
      activeKeyRef.current = null;
      if (registeredRef.current) unregisterEncryptionKey(token);
    };
  }, [token]);

  // Firefox (and Chrome) terminate an idle SW after ~30s. Once handleDownload
  // has returned the streamed Response via respondWith, no further events
  // reach the worker — the browser considers it idle mid-download, kills it,
  // and the ciphertext stream aborts. Ping every 10s while the download page
  // is up (and the SW is ready to serve) to keep it alive. Only spun up for
  // encrypted transfers — legacy plaintext downloads go 302 → S3 direct and
  // don't touch the SW.
  useEffect(() => {
    if (!isEncrypted || encryptionState !== "ready") return;
    return startServiceWorkerKeepalive();
  }, [isEncrypted, encryptionState]);

  // Coming back to the tab (or a bfcache restore): the keepalive was
  // throttled while hidden and the worker may have been replaced. The
  // store covers the next download either way; re-registering here just
  // warms the new instance so the click doesn't pay the IDB round-trip.
  useEffect(() => {
    if (!isEncrypted || encryptionState !== "ready") return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshEncryptionKey();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pageshow", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pageshow", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEncrypted, encryptionState]);

  const submitPastedKey = async () => {
    const key = pastedKey.trim();
    if (!key) return;
    setPasteError(false);
    setEncryptionState("loading");
    ++registerAttemptRef.current;
    try {
      const ok = await registerKey(key);
      if (!mountedRef.current) {
        // The recipient navigated away mid-registration. Drop the key we
        // just parked in the SW so it doesn't outlive the page. No
        // "newer attempt" exemption here: after unmount nobody owns the
        // token, and a later attempt may have failed and left ours behind.
        if (ok) {
          unregisterEncryptionKey(token);
          registeredRef.current = false;
        }
        return;
      }
      setEncryptionState(ok ? "ready" : "need-key");
      if (!ok) setPasteError(true);
    } catch {
      if (!mountedRef.current) return;
      // Malformed key (bad base64 / wrong length). A valid-length but wrong
      // key registers fine and instead fails at download time.
      setEncryptionState("need-key");
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
  const triggerDownload = async (file: (typeof transfer.files)[number]) => {
    if (isEncrypted) {
      // Re-register the key immediately before opening the iframe. In the
      // healthy path the SW is already alive (the keepalive is ticking) and
      // this is a cheap idempotent no-op (~10ms handshake). In the edge
      // case where the SW died anyway (mobile tab was backgrounded long
      // enough for setInterval to be throttled below the idle threshold,
      // browser bug, etc.), this spins it back up + reloads the key so
      // the click doesn't 500 with "Decryption key not loaded". Fail
      // closed: no iframe if the refresh didn't succeed — better a
      // no-op click than a broken download.
      ++registerAttemptRef.current;
      const ok = await refreshEncryptionKey();
      if (!mountedRef.current) {
        // The recipient navigated away while the handshake was in flight.
        // The unmount cleanup already sent an unregister, but the SW
        // applies registrations asynchronously (importKey), so ours may
        // have landed *after* that delete and the key would outlive the
        // page. Drop it again — unconditionally, nobody owns the token
        // after unmount — and don't bolt an iframe onto a page that's
        // gone. Same guard as submitPastedKey and the auto-register effect.
        if (ok) {
          unregisterEncryptionKey(token);
          registeredRef.current = false;
        }
        return;
      }
      if (!ok) return;
      const requestId = crypto.randomUUID();
      requestsRef.current.set(requestId, file.id);
      setPending((prev) => new Map(prev).set(requestId, file.id));
      const resume = interruptedRef.current.delete(file.id);
      setInterruptedIds((prev) => {
        if (!prev.has(file.id)) return prev;
        const next = new Set(prev);
        next.delete(file.id);
        return next;
      });
      const iframe = document.createElement("iframe");
      iframe.style.display = "none";
      iframe.src = streamingDownloadUrl(
        token,
        file.id,
        file.filename,
        recipientToken,
        requestId,
        resume,
      );
      document.body.appendChild(iframe);
      iframesRef.current.set(requestId, iframe);
    } else {
      downloadFile(token, file.id, recipientToken);
    }
  };
  const anyPreparing = preparingIds.size > 0;
  const downloadAll = () => {
    downloadableFiles.forEach((file, i) => {
      setTimeout(() => {
        if (isEncrypted) {
          void triggerDownload(file);
        } else {
          downloadFileInIframe(token, file.id, recipientToken);
        }
      }, i * 800);
    });
  };

  // Infected / pending never reach a recipient (the scan gates creation). What
  // does reach them is files never scanned at all — say so: "clean" is a claim
  // we can only make when we actually looked.
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
    if (status === "too_large" || status === "skipped") {
      const reason =
        status === "too_large"
          ? t("This file was not scanned for viruses because it is too large.")
          : transfer.confidential
            ? t(
                "Confidential transfer: this file is encrypted, so our antivirus couldn't check it.",
              )
            : t("This file was not scanned for viruses.");
      return (
        <Tooltip content={reason} placement="top">
          <span className="file-item__scan file-item__scan--warning">
            <Warning />
            {t("Not scanned")}
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
              <span className="download-view__meta-item download-view__meta-item--encryption">
                <Lock />
                {t("Confidential")}
              </span>
            </Tooltip>
          </>
        )}
      </div>

      <hr className="download-view__divider" />

      {/* All page-level callouts share this block so the reader takes them
          in as a single glance. Order: ERROR → WARNING; within warnings,
          most-actionable first (auto-archive can be fixed by not clicking
          "Download all" carelessly; the confidential / scan-not-verified
          notices are informational). Confidential and the generic
          "some files not scanned" alerts are mutually exclusive —
          confidential means no scan by design, so its dedicated banner
          already covers the "no scan" outcome for every file. */}
      {isEncrypted && encryptionState === "error" && (
        <Alert
          type={VariantType.ERROR}
          className="download-view__encryption-error-alert"
        >
          {t(
            "We couldn't set up decryption in your browser. Try a different browser or make sure yours is up to date.",
          )}
        </Alert>
      )}

      {isOwner && recipientToken && transfer.notify_on_download && (
        <Alert type={VariantType.INFO} className="download-view__owner-alert">
          {t(
            "You are signed in as the sender: your own visits and downloads are not recorded, so this recipient's status won't change and no download receipt will be sent. Open the link in a private window to test it.",
          )}
        </Alert>
      )}

      {interruptedIds.size > 0 && (
        <Alert
          type={VariantType.WARNING}
          className="download-view__interrupted-alert"
        >
          {t(
            "The download of {{names}} was interrupted. On Firefox, Resume and Retry from the downloads panel don't work: click the file again here to start it over.",
            {
              names: transfer.files
                .filter((f) => interruptedIds.has(f.id))
                .map((f) => f.filename)
                .join(", "),
            },
          )}
        </Alert>
      )}

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

      {transfer.confidential && transfer.files.length > 0 && (
        <Alert
          type={VariantType.WARNING}
          className="download-view__scan-alert"
        >
          {t(
            "Confidential transfer: the sender encrypted these files and only your browser can open them. Our antivirus couldn't check them, so make sure you know the sender before opening them.",
          )}
        </Alert>
      )}

      {!transfer.confidential &&
        hasUnscannedFiles(transfer.files, (f) => f.scan_status) && (
          <Alert
            type={VariantType.WARNING}
            className="download-view__scan-alert"
          >
            {t(
              "Some files in this transfer couldn't be scanned for viruses. Open them with caution.",
            )}
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
                    icon={
                      preparingIds.has(file.id) ? <ButtonSpinner /> : <Download />
                    }
                    disabled={
                      !downloadable ||
                      expired ||
                      encryptionState !== "ready" ||
                      preparingIds.has(file.id)
                    }
                    onClick={() => void triggerDownload(file)}
                    aria-label={t("Download {{name}}", { name: file.filename })}
                    title={
                      expired
                        ? t("This transfer has expired.")
                        : !downloadable
                          ? t("Available once the antivirus scan passes")
                          : encryptionState === "ready" &&
                              !preparingIds.has(file.id)
                            ? t("Download")
                            : t("Preparing your download…")
                    }
                  />
                }
              />
            );
          })}
        </ul>
      )}

      {isEncrypted && encryptionState === "need-key" && (
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
      {downloadableFiles.length > 0 && (
        <Button
          color="brand"
          icon={
            (isEncrypted && encryptionState === "loading") || anyPreparing ? (
              <ButtonSpinner />
            ) : (
              <Download />
            )
          }
          fullWidth
          onClick={downloadAll}
          disabled={expired || encryptionState !== "ready" || anyPreparing}
          className="download-view__download-all"
        >
          {expired
            ? t("Transfer expired")
            : (isEncrypted && encryptionState === "loading") || anyPreparing
              ? t("Preparing your download…")
              : t("Download all")}
        </Button>
      )}
    </div>
  );
}
