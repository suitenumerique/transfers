import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  LabelledBox,
  Loader,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { DropdownMenu, Icon, useDropdownMenu } from "@gouvfr-lasuite/ui-kit";
import type { SharingMode } from "@/features/api/types";
import { useConfig } from "@/features/providers/config";
import {
  fileKey,
  useTransferDraft,
  type DraftFile,
  type DrivePickedItem,
} from "../api/useTransferDraft";
import { DriveAttachButton } from "./DriveAttachButton";
import { FileDropZone } from "./FileDropZone";
import { RecipientInput } from "./RecipientInput";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function StorageGauge({
  currentSize,
  maxSize,
}: {
  currentSize: number;
  maxSize: number;
}) {
  const pct = Math.min((currentSize / maxSize) * 100, 100);
  return (
    <div className="transfer-form__gauge">
      <div className="transfer-form__gauge-meta">
        <span>
          {formatBytes(currentSize)} {"·"} {formatBytes(maxSize)}{" "}
          {/* used / total */}
        </span>
      </div>
      <div className="transfer-form__gauge-track">
        <div
          className="transfer-form__gauge-fill"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

const EXPIRY_CHOICES = [7, 30, 90];

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
          size: formatBytes(oversized.size),
          max: formatBytes(config.TRANSFER_MAX_FILE_SIZE),
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
          max: formatBytes(config.TRANSFER_MAX_TOTAL_SIZE),
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
          size: formatBytes(oversized.size),
          max: formatBytes(config.TRANSFER_MAX_FILE_SIZE),
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
          max: formatBytes(config.TRANSFER_MAX_TOTAL_SIZE),
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
      const finalized = await draft.submit({
        title,
        expires_in_days: expiresInDays,
        sharing_mode: sharingMode,
        recipients: sharingMode === "email" ? recipients : [],
      });
      await router.push(`/transfers/${finalized.id}`);
    } catch {
      // Errors surface via draft.error / per-file state; no-op here.
    }
  };

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
            compact={hasFiles}
            extraCta={
              config.DRIVE ? (
                <DriveAttachButton
                  onPick={handleDrivePick}
                  onError={setFileError}
                  disabled={busy}
                  maxFileSize={config.TRANSFER_MAX_FILE_SIZE}
                />
              ) : undefined
            }
          />
          {/* extraCta now rides inside the FileDropZone in compact mode
              too, so no external Drive CTA below the file list. */}

          {hasFiles && (
            <ul
              className="transfer-form__file-list"
              aria-label={t("Selected files")}
            >
              {draft.files.map((df) => (
                <li
                  key={df.key}
                  className={`transfer-form__file-item transfer-form__file-item--${df.state}`}
                >
                  <span
                    className="transfer-form__file-icon-tile"
                    aria-hidden="true"
                  >
                    {df.state === "registering" || df.state === "importing" ? (
                      <Loader size="small" />
                    ) : df.state === "done" ? (
                      <Icon name="check_circle" />
                    ) : df.state === "error" ? (
                      <Icon name="error_outline" />
                    ) : df.sourceUrl ? (
                      <Icon name="folder_open" />
                    ) : (
                      <Icon name="description" />
                    )}
                  </span>
                  <div className="transfer-form__file-info">
                    <span className="transfer-form__file-name">{df.name}</span>
                    <span className="transfer-form__file-meta">
                      {df.state === "uploading"
                        ? `${formatBytes(df.loaded)} / ${formatBytes(df.total)} · ${percent(df)}%`
                        : df.state === "importing"
                          ? `${formatBytes(df.total)} · ${t("Importing...")}`
                          : df.state === "error"
                            ? (df.error ?? t("Error creating transfer."))
                            : df.state === "done"
                              ? `${formatBytes(df.total)} · ${t("Ready")}`
                              : formatBytes(df.total)}
                    </span>
                    {df.state === "uploading" && (
                      <div
                        className="transfer-form__file-progress"
                        role="progressbar"
                        aria-valuenow={percent(df)}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <div
                          className="transfer-form__file-progress-fill"
                          style={{ width: `${percent(df)}%` }}
                        />
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="transfer-form__file-remove"
                    onClick={() => {
                      void draft.removeFile(df.key);
                    }}
                    disabled={busy}
                    aria-label={t("Remove {{name}}", { name: df.name })}
                    title={t("Remove")}
                  >
                    <Icon name="close" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {fileError && <Alert type={VariantType.ERROR}>{fileError}</Alert>}
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
              <Icon name="mail" />
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
                setRecipients([]);
              }}
              disabled={busy}
            >
              <Icon name="link" />
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

          <Button type="submit" fullWidth disabled={submitDisabled}>
            {busy
              ? t("Sending...")
              : sharingMode === "email"
                ? hasFiles
                  ? t("Send {{count}} item", { count: draft.files.length })
                  : t("Send")
                : t("Create link")}
          </Button>
        </section>
      </div>
    </form>
  );
}
