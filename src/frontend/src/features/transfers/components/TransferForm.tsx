import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  LabelledBox,
  Tooltip,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import {
  ArrowUpCircle,
  ArrowUpDown,
  ArrowUpRight,
  Checkmark,
  Copy,
  Doc,
  DropdownMenu,
  FileCheck,
  FileError,
  FolderDrive,
  Icon,
  Info,
  Link as LinkIcon,
  Mail,
  MailCheckFilled,
  useDropdownMenu,
} from "@gouvfr-lasuite/ui-kit";
import type { SharingMode, TransferDetail } from "@/features/api/types";
import { useConfig } from "@/features/providers/config";
import { formatFileSize } from "@/features/utils/string-helper";
import {
  fileKey,
  useTransferDraft,
  type DraftFile,
  type DrivePickedItem,
} from "../api/useTransferDraft";
import { DriveAttachButton } from "./DriveAttachButton";
import { FileDropZone } from "./FileDropZone";
import { FileItem } from "./FileItem";
import { RecipientInput } from "./RecipientInput";

function StorageGauge({
  currentSize,
  maxSize,
}: {
  currentSize: number;
  maxSize: number;
}) {
  const pct = Math.min((currentSize / maxSize) * 100, 100);
  // Traffic-light fill colour based on fullness. Thresholds picked so a
  // casually-filled form stays neutral grey (plenty of headroom), the bar
  // warns in orange past 75 % (user is approaching the cap, last chance to
  // drop a file), and goes red on 90 %+ (next file likely rejected).
  const level = pct >= 90 ? "danger" : pct >= 75 ? "warning" : "neutral";
  return (
    <div className="transfer-form__gauge">
      <div className="transfer-form__gauge-meta">
        <span>
          {formatFileSize(currentSize)} {"·"} {formatFileSize(maxSize)}{" "}
          {/* used / total */}
        </span>
      </div>
      <div className="transfer-form__gauge-track">
        <div
          className={`transfer-form__gauge-fill transfer-form__gauge-fill--${level}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

const EXPIRY_CHOICES = [7, 30, 90];

// Small 16px spinner used as the submit button's `icon` while the form
// waits for uploads to finish + finalize to return. Inherits currentColor
// so it shows white on the filled brand button.
function ButtonSpinner() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="file-item__ring file-item__ring--spin"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.35"
        strokeWidth="2.5"
      />
      <path
        d="M12 3a9 9 0 0 1 9 9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

// Indeterminate spinner used while a Fichiers import runs server-side.
// Plain CSS rotation — the SVG node itself is stable across draft
// re-renders (row `key` is df.key, which doesn't change during polling),
// so the animation keeps spinning without resetting every 2s tick.
function ImportSpinner() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="file-item__ring file-item__ring--spin"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.18"
        strokeWidth="2"
      />
      <path
        d="M12 3a9 9 0 0 1 9 9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

// 24×24 progress ring for an uploading file row. Stroke-dasharray
// shrinks as percent grows so the brand-colored arc stretches clockwise
// starting from the top. Clamped to [0, 100] in case upstream reports
// floats / overshoot.
function UploadRing({ percent }: { percent: number }) {
  const p = Math.max(0, Math.min(100, percent));
  const radius = 9;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - p / 100);
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="file-item__ring"
    >
      <circle
        cx="12"
        cy="12"
        r={radius}
        stroke="currentColor"
        strokeOpacity="0.18"
        strokeWidth="2"
      />
      <circle
        cx="12"
        cy="12"
        r={radius}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 12 12)"
        style={{ transition: "stroke-dashoffset 150ms linear" }}
      />
    </svg>
  );
}

function stripExtension(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

function percent(df: DraftFile): number {
  if (df.total === 0) return 0;
  return Math.min(100, Math.round((df.loaded / df.total) * 100));
}

export function TransferForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const config = useConfig();
  const draft = useTransferDraft();

  const [title, setTitle] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<number>(30);
  const [sharingMode, setSharingMode] = useState<SharingMode>("email");
  const [recipients, setRecipients] = useState<string[]>([]);
  const [hasValidPending, setHasValidPending] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  // Opt-in: once every file has been downloaded at least once, the backend
  // auto-deactivates the transfer (status flip + scheduled S3 wipe).
  // Matches a "one-shot link" intent.
  const [autoArchiveOnDownload, setAutoArchiveOnDownload] = useState(false);
  // Once finalize resolves we pivot the whole form to a success panel (see
  // TransferSuccess below). Clicking "New transfer" clears this and the
  // other form state so the user starts fresh on the same route.
  const [finalized, setFinalized] = useState<TransferDetail | null>(null);
  const expiryMenu = useDropdownMenu();

  // Abort the draft on unmount so dropping a file and navigating away doesn't
  // leave bytes hanging in S3 for 24h (the server cleanup cron catches it
  // eventually, but we can reclaim immediately here).
  useEffect(() => {
    return () => {
      void draft.abort();
    };
  }, []);

  const handleFilesChange = (incoming: File[]) => {
    setFileError(null);

    const oversized = incoming.find(
      (f) => f.size > config.TRANSFER_MAX_FILE_SIZE,
    );
    if (oversized) {
      setFileError(
        t("File too large: {{name}} ({{size}}). Maximum: {{max}}.", {
          name: oversized.name,
          size: formatFileSize(oversized.size),
          max: formatFileSize(config.TRANSFER_MAX_FILE_SIZE),
        }),
      );
      return;
    }

    // Dedupe against the draft's current file list.
    const existingKeys = new Set(draft.files.map((f) => f.key));
    const newFiles = incoming.filter((f) => !existingKeys.has(fileKey(f)));

    if (
      draft.files.length + newFiles.length >
      config.TRANSFER_MAX_FILES_PER_TRANSFER
    ) {
      setFileError(
        t("Too many files. Maximum: {{max}}.", {
          max: config.TRANSFER_MAX_FILES_PER_TRANSFER,
        }),
      );
      return;
    }

    const currentTotal = draft.files.reduce((sum, f) => sum + f.total, 0);
    const addedTotal = newFiles.reduce((sum, f) => sum + f.size, 0);
    if (currentTotal + addedTotal > config.TRANSFER_MAX_TOTAL_SIZE) {
      setFileError(
        t("Total size exceeds the limit of {{max}}.", {
          max: formatFileSize(config.TRANSFER_MAX_TOTAL_SIZE),
        }),
      );
      return;
    }

    for (const f of newFiles) {
      draft.addFile(f);
    }

    // Auto-fill the title from the first file ever dropped so users who drop
    // and submit immediately get a reasonable default. Once the user edits
    // the title, leave it alone.
    if (
      newFiles.length > 0 &&
      title.trim() === "" &&
      draft.files.length === 0
    ) {
      setTitle(stripExtension(newFiles[0].name));
    }
  };

  const handleDrivePick = (items: DrivePickedItem[]) => {
    setFileError(null);

    const oversized = items.find(
      (it) => it.size > config.TRANSFER_MAX_FILE_SIZE,
    );
    if (oversized) {
      setFileError(
        t("File too large: {{name}} ({{size}}). Maximum: {{max}}.", {
          name: oversized.filename,
          size: formatFileSize(oversized.size),
          max: formatFileSize(config.TRANSFER_MAX_FILE_SIZE),
        }),
      );
      return;
    }

    // Same cumulative guards as local drops.
    if (
      draft.files.length + items.length >
      config.TRANSFER_MAX_FILES_PER_TRANSFER
    ) {
      setFileError(
        t("Too many files. Maximum: {{max}}.", {
          max: config.TRANSFER_MAX_FILES_PER_TRANSFER,
        }),
      );
      return;
    }

    const currentTotal = draft.files.reduce((sum, f) => sum + f.total, 0);
    const addedTotal = items.reduce((sum, it) => sum + it.size, 0);
    if (currentTotal + addedTotal > config.TRANSFER_MAX_TOTAL_SIZE) {
      setFileError(
        t("Total size exceeds the limit of {{max}}.", {
          max: formatFileSize(config.TRANSFER_MAX_TOTAL_SIZE),
        }),
      );
      return;
    }

    draft.attachFromDrive(items);

    if (
      items.length > 0 &&
      title.trim() === "" &&
      draft.files.length === 0
    ) {
      setTitle(stripExtension(items[0].filename));
    }
  };

  const hasFiles = draft.files.length > 0;
  const currentSize = draft.files.reduce((sum, f) => sum + f.total, 0);
  const anyError = draft.files.some((f) => f.state === "error");
  const busy = draft.isSubmitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hasFiles || anyError || busy) return;

    if (sharingMode === "email" && recipients.length === 0 && !hasValidPending) {
      return;
    }

    try {
      const result = await draft.submit({
        title,
        expires_in_days: expiresInDays,
        sharing_mode: sharingMode,
        recipients: sharingMode === "email" ? recipients : [],
        auto_archive_on_download: autoArchiveOnDownload,
      });
      setFinalized(result);
    } catch {
      // Errors surface via draft.error / per-file state; no-op here.
    }
  };

  const handleNewTransfer = () => {
    setFinalized(null);
    setTitle("");
    setRecipients([]);
    setHasValidPending(false);
    setFileError(null);
  };

  // The sidebar's "New transfer" link points to `/`. When the user is
  // already on `/` viewing a success panel, Next.js Link is a no-op and
  // `finalized` stays set. The Sidebar dispatches this event on click so
  // we bounce back to the empty form regardless of current route state.
  useEffect(() => {
    const handler = () => handleNewTransfer();
    window.addEventListener("transferts:new-transfer", handler);
    return () => window.removeEventListener("transferts:new-transfer", handler);
  }, []);

  const expiryOptions = EXPIRY_CHOICES.map((days) => ({
    label: t("{{count}} days", { count: days }),
    value: String(days),
    callback: () => setExpiresInDays(days),
  }));
  const currentExpiryLabel = t("{{count}} days", { count: expiresInDays });

  const submitDisabled =
    !hasFiles ||
    anyError ||
    busy ||
    (sharingMode === "email" && recipients.length === 0 && !hasValidPending);

  if (finalized) {
    return (
      <TransferSuccess
        transfer={finalized}
        onNewTransfer={handleNewTransfer}
        onGoToDetail={() => router.push(`/transfers/${finalized.id}`)}
      />
    );
  }

  return (
    <form onSubmit={handleSubmit} className="transfer-form">
      <div className="transfer-form__grid">
        <section
          className="transfer-form__files-col"
          aria-label={t("Your items")}
        >
          <header className="transfer-form__files-header">
            <h1 className="transfer-form__files-title">
              {hasFiles
                ? t("{{count}} item", { count: draft.files.length })
                : t("Your items")}
            </h1>
            {hasFiles && (
              <StorageGauge
                currentSize={currentSize}
                maxSize={config.TRANSFER_MAX_TOTAL_SIZE}
              />
            )}
          </header>

          <FileDropZone
            onChange={handleFilesChange}
            errorMessage={fileError}
          />
          {config.DRIVE && (
            <DriveAttachButton
              variant="link"
              onPick={handleDrivePick}
              onError={setFileError}
              disabled={busy}
              maxFileSize={config.TRANSFER_MAX_FILE_SIZE}
            />
          )}

          {hasFiles && (
            <ul
              className="transfer-form__file-list"
              aria-label={t("Selected files")}
            >
              {draft.files.map((df) => {
                const pct = percent(df);
                const isUploading = df.state === "uploading";
                const isDone = df.state === "done";
                const icon = isUploading ? (
                  <UploadRing percent={pct} />
                ) : df.state === "registering" || df.state === "importing" ? (
                  <ImportSpinner />
                ) : isDone ? (
                  <FileCheck />
                ) : df.state === "error" ? (
                  <FileError />
                ) : df.sourceUrl ? (
                  <FolderDrive />
                ) : (
                  <Doc />
                );
                // `state` on FileItem drives the icon color (default /
                // success / error). The "uploading" and "importing" stages
                // keep the brand default — they're transient.
                const itemState =
                  df.state === "done"
                    ? "done"
                    : df.state === "error"
                      ? "error"
                      : "default";
                const extras = (
                  <>
                    {isUploading && (
                      <span
                        className="file-item__pct"
                        role="progressbar"
                        aria-valuenow={pct}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        {pct}%
                      </span>
                    )}
                    {df.state === "importing" && (
                      <span className="file-item__pct">
                        {t("Importing...")}
                      </span>
                    )}
                    {df.state === "error" && (
                      <span className="file-item__error-text">
                        {df.error ?? t("Error creating transfer.")}
                      </span>
                    )}
                  </>
                );
                const action = (
                  <button
                    type="button"
                    className={`transfer-form__file-action${
                      isUploading ? " transfer-form__file-action--cancel" : ""
                    }`}
                    onClick={() => {
                      // Removing a file re-evaluates the cumulative limits,
                      // so an existing dropzone error is no longer relevant.
                      setFileError(null);
                      void draft.removeFile(df.key);
                    }}
                    disabled={busy}
                  >
                    {isUploading ? t("Cancel") : t("Delete")}
                  </button>
                );
                return (
                  <FileItem
                    key={df.key}
                    icon={icon}
                    name={df.name}
                    size={formatFileSize(df.total)}
                    state={itemState}
                    extras={extras}
                    action={action}
                  />
                );
              })}
            </ul>
          )}

          {/* File-level rejection errors now render inside the dropzone
              (passed via errorMessage). Keep the draft-level Alert for
              per-file upload failures that aren't input-validation. */}
          {draft.error && anyError && (
            <Alert type={VariantType.ERROR}>{draft.error}</Alert>
          )}
        </section>

        <section className="transfer-form__options-col">
          <div
            className="transfer-form__tabs"
            role="tablist"
            aria-label={t("Sharing mode")}
          >
            <button
              type="button"
              role="tab"
              aria-selected={sharingMode === "email"}
              className={`transfer-form__tab${
                sharingMode === "email" ? " transfer-form__tab--active" : ""
              }`}
              onClick={() => setSharingMode("email")}
              disabled={busy}
            >
              <Mail />
              <span>{t("Email")}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={sharingMode === "link"}
              className={`transfer-form__tab${
                sharingMode === "link" ? " transfer-form__tab--active" : ""
              }`}
              onClick={() => setSharingMode("link")}
              disabled={busy}
            >
              <LinkIcon />
              <span>{t("Link")}</span>
            </button>
          </div>

          {sharingMode === "email" && (
            <LabelledBox label={t("Send to")} variant="classic">
              <RecipientInput
                recipients={recipients}
                onChange={setRecipients}
                onPendingChange={setHasValidPending}
                disabled={busy}
              />
            </LabelledBox>
          )}

          <Input
            label={t("Title")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("Enter a title")}
            disabled={busy}
            variant="classic"
            fullWidth
            maxLength={80}
          />

          <div className="transfer-form__validity">
            <span className="transfer-form__validity-label">
              {t("Validity duration")}
            </span>
            <DropdownMenu
              options={expiryOptions}
              selectedValues={[String(expiresInDays)]}
              isOpen={expiryMenu.isOpen}
              onOpenChange={expiryMenu.setIsOpen}
            >
              <button
                type="button"
                className="transfer-form__validity-trigger"
                disabled={busy}
                aria-label={t("Validity duration")}
                onClick={() => expiryMenu.setIsOpen(!expiryMenu.isOpen)}
              >
                <span>{currentExpiryLabel}</span>
                <Icon name="keyboard_arrow_down" />
              </button>
            </DropdownMenu>
          </div>

          <div className="transfer-form__auto-archive">
            <Checkbox
              label={t("Deactivate after all files are downloaded")}
              checked={autoArchiveOnDownload}
              onChange={(e) =>
                setAutoArchiveOnDownload(e.currentTarget.checked)
              }
              disabled={busy}
            />
            <Tooltip
              content={t(
                "Once every file has been downloaded at least once, the transfer is automatically deactivated: the download link stops working and the files are wiped from our servers.",
              )}
              placement="top"
            >
              <button
                type="button"
                className="transfer-form__auto-archive-help"
                aria-label={t("More information")}
                tabIndex={0}
              >
                <Info />
              </button>
            </Tooltip>
          </div>

          <Button
            type="submit"
            fullWidth
            disabled={submitDisabled}
            icon={
              busy ? (
                <ButtonSpinner />
              ) : sharingMode === "email" ? (
                <ArrowUpRight />
              ) : (
                <Copy />
              )
            }
          >
            {busy
              ? t("Sending...")
              : sharingMode === "email"
                ? hasFiles
                  ? t("Send {{count}} item", { count: draft.files.length })
                  : t("Send")
                : t("Create link")}
          </Button>

          {busy && (
            <p className="transfer-form__submit-hint" role="status">
              {t(
                "Your transfer will be created once the upload finishes. Keep this tab open.",
              )}
            </p>
          )}
        </section>
      </div>
    </form>
  );
}

function formatExpiry(iso: string): string {
  // Matches the Figma mock: "25/12/2026 à 00h00". We split on `à` so the
  // date and time chunks can be wrapped in <strong> separately.
  const d = new Date(iso);
  const date = d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  const time = d.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  }).replace(":", "h");
  return `${date}|${time}`;
}

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(1, Math.round(ms / (24 * 60 * 60 * 1000)));
}

function TransferSuccess({
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
        <Button
          color="brand"
          icon={<ArrowUpCircle />}
          onClick={onGoToDetail}
        >
          {t("View summary")}
        </Button>
      </div>
    </div>
  );
}
