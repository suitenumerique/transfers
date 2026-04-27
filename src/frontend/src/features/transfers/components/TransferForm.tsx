import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  LabelledBox,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import {
  ArrowUpRight,
  Copy,
  Doc,
  DropdownMenu,
  FileCheck,
  FileError,
  FolderDrive,
  Icon,
  Link as LinkIcon,
  Mail,
  useDropdownMenu,
} from "@gouvfr-lasuite/ui-kit";
import type { SharingMode } from "@/features/api/types";
import { useConfig } from "@/features/providers/config";
import { formatFileSize } from "@/features/utils/string-helper";
import {
  fileKey,
  SubmitCancelledError,
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
  const awaitingUploads = draft.isAwaitingUploads;
  const finalizing = draft.isFinalizing;
  // Metadata inputs / Drive attach / tabs stay locked for the whole
  // submit flow — `busy` gates those. File-level Delete / Cancel actions
  // only need to lock during the non-cancellable finalize window so the
  // user can still back out of an armed auto-create.
  const busy = awaitingUploads || finalizing;
  const fileActionsDisabled = finalizing;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Button is disabled during both phases — the form can still submit
    // via Enter key, so guard here too.
    if (busy) return;
    if (!hasFiles || anyError) return;

    if (sharingMode === "email" && recipients.length === 0 && !hasValidPending) {
      return;
    }

    try {
      const result = await draft.submit({
        title,
        expires_in_days: expiresInDays,
        sharing_mode: sharingMode,
        recipients: sharingMode === "email" ? recipients : [],
      });
      // Hand off to the dedicated confirm route — the form unmounts, so
      // the sidebar logo and "New transfer" link work as plain Next.js
      // navigation back to ``/`` without an in-place pivot hack.
      router.push(`/confirm/${result.id}`);
    } catch (err) {
      // A cancel is a deliberate user action — stay on the form silently.
      // Other errors already surface via draft.error / per-file state.
      if (err instanceof SubmitCancelledError) return;
    }
  };

  const expiryOptions = EXPIRY_CHOICES.map((days) => ({
    label: t("{{count}} days", { count: days }),
    value: String(days),
    callback: () => setExpiresInDays(days),
  }));
  const currentExpiryLabel = t("{{count}} days", { count: expiresInDays });

  // Submit button stays disabled during both submit phases. To back out
  // of an armed auto-create, the user clicks Delete/Cancel on a file row
  // (those stay enabled while awaitingUploads, and their handler disarms
  // the pending finalize).
  const submitDisabled =
    busy ||
    !hasFiles ||
    anyError ||
    (sharingMode === "email" && recipients.length === 0 && !hasValidPending);

  return (
    <form onSubmit={handleSubmit} className="transfer-form">
      <div className="transfer-form__grid">
        <section
          className="transfer-form__files-col"
          aria-label={t("Create a new transfer")}
        >
          <header className="transfer-form__files-header">
            <h1 className="transfer-form__files-title">
              {hasFiles
                ? t("{{count}} file", { count: draft.files.length })
                : t("Create a new transfer")}
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
              disabled={finalizing}
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
                    disabled={fileActionsDisabled}
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
              onClick={() => {
                setSharingMode("email");
                // Switching sharing mode is a draft-level change — disarm
                // any pending auto-finalize so the user re-confirms.
                draft.cancelSubmit();
              }}
              disabled={finalizing}
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
              onClick={() => {
                setSharingMode("link");
                draft.cancelSubmit();
              }}
              disabled={finalizing}
            >
              <LinkIcon />
              <span>{t("Link")}</span>
            </button>
          </div>

          {sharingMode === "email" && (
            <LabelledBox label={t("Send to")} variant="classic">
              <RecipientInput
                recipients={recipients}
                onChange={(next) => {
                  setRecipients(next);
                  // Editing the recipient list while auto-finalize is armed
                  // means intent has shifted — disarm so the user has to
                  // explicitly re-send.
                  draft.cancelSubmit();
                }}
                onPendingChange={setHasValidPending}
                disabled={finalizing}
              />
            </LabelledBox>
          )}

          <Input
            label={t("Title")}
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
              draft.cancelSubmit();
            }}
            placeholder={t("Enter a title")}
            disabled={finalizing}
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
            {finalizing
              ? t("Sending...")
              : awaitingUploads
                ? sharingMode === "email"
                  ? t("Sending after uploads finish")
                  : t("Creating after uploads finish")
                : sharingMode === "email"
                  ? hasFiles
                    ? t("Send {{count}} file", { count: draft.files.length })
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

