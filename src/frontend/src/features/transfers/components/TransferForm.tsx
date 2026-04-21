import { useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  LabelledBox,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { DropdownMenu, Icon, useDropdownMenu } from "@gouvfr-lasuite/ui-kit";
import type { SharingMode } from "@/features/api/types";
import { useConfig } from "@/features/providers/config";
import {
  useCreateTransfer,
  type AggregateProgress,
} from "../api/useCreateTransfer";
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

export function TransferForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const config = useConfig();
  const [uploadProgress, setUploadProgress] =
    useState<AggregateProgress | null>(null);
  const createTransfer = useCreateTransfer({
    onProgress: (progress) => setUploadProgress(progress),
  });
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<number>(30);
  const [sharingMode, setSharingMode] = useState<SharingMode>("email");
  const [recipients, setRecipients] = useState<string[]>([]);
  const [hasValidPending, setHasValidPending] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const expiryMenu = useDropdownMenu();

  const handleFilesChange = (incoming: File[]) => {
    setFileError(null);

    const oversized = incoming.filter(
      (f) => f.size > config.TRANSFER_MAX_FILE_SIZE,
    );
    if (oversized.length > 0) {
      setFileError(
        t("File too large: {{name}} ({{size}}). Maximum: {{max}}.", {
          name: oversized[0].name,
          size: formatBytes(oversized[0].size),
          max: formatBytes(config.TRANSFER_MAX_FILE_SIZE),
        }),
      );
      return;
    }

    setFiles((prev) => {
      const key = (f: File) => `${f.name}|${f.size}|${f.lastModified}`;
      const existing = new Set(prev.map(key));
      const newFiles = incoming.filter((f) => !existing.has(key(f)));
      const merged = [...prev, ...newFiles];

      if (merged.length > config.TRANSFER_MAX_FILES_PER_TRANSFER) {
        setFileError(
          t("Too many files. Maximum: {{max}}.", {
            max: config.TRANSFER_MAX_FILES_PER_TRANSFER,
          }),
        );
        return prev;
      }

      const totalSize = merged.reduce((sum, f) => sum + f.size, 0);
      if (totalSize > config.TRANSFER_MAX_TOTAL_SIZE) {
        setFileError(
          t("Total size exceeds the limit of {{max}}.", {
            max: formatBytes(config.TRANSFER_MAX_TOTAL_SIZE),
          }),
        );
        return prev;
      }

      return merged;
    });
    if (incoming.length > 0 && title.trim() === "") {
      setTitle(stripExtension(incoming[0].name));
    }
  };

  const removeFile = (index: number) => {
    setFileError(null);
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const busy = createTransfer.isPending;
  const hasFiles = files.length > 0;
  const currentSize = files.reduce((sum, f) => sum + f.size, 0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return;

    if (sharingMode === "email" && recipients.length === 0 && !hasValidPending) {
      return;
    }

    try {
      setUploadProgress({
        fileIndex: 0,
        fileCount: files.length,
        fileName: files[0].name,
        fileLoaded: 0,
        fileTotal: files[0].size,
        totalLoaded: 0,
        totalTotal: files.reduce((a, f) => a + f.size, 0),
      });
      const created = await createTransfer.mutateAsync({
        title,
        expires_in_days: expiresInDays,
        files,
        sharing_mode: sharingMode,
        recipients: sharingMode === "email" ? recipients : undefined,
      });
      await router.push(`/transfers/${created.id}`);
    } catch {
      setUploadProgress(null);
    }
  };

  const expiryOptions = EXPIRY_CHOICES.map((days) => ({
    label: t("{{count}} days", { count: days }),
    value: String(days),
    callback: () => setExpiresInDays(days),
  }));
  const currentExpiryLabel = t("{{count}} days", { count: expiresInDays });

  const disabled = !hasFiles || busy;
  const submitDisabled =
    disabled ||
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
                ? t("{{count}} item", { count: files.length })
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
                  onPick={handleFilesChange}
                  onError={setFileError}
                  disabled={busy}
                  maxFileSize={config.TRANSFER_MAX_FILE_SIZE}
                />
              ) : undefined
            }
          />

          {hasFiles && (
            <ul
              className="transfer-form__file-list"
              aria-label={t("Selected files")}
            >
              {files.map((f, i) => (
                <li
                  key={`${f.name}-${f.size}-${f.lastModified}`}
                  className="transfer-form__file-item"
                >
                  <span
                    className="transfer-form__file-icon-tile"
                    aria-hidden="true"
                  >
                    <Icon name="description" />
                  </span>
                  <div className="transfer-form__file-info">
                    <span className="transfer-form__file-name">{f.name}</span>
                    <span className="transfer-form__file-meta">
                      {formatBytes(f.size)}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="transfer-form__file-remove"
                    onClick={() => removeFile(i)}
                    disabled={busy}
                    aria-label={t("Remove {{name}}", { name: f.name })}
                    title={t("Remove")}
                  >
                    <Icon name="close" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {hasFiles && config.DRIVE && (
            // In compact mode the dropzone hides its extraCta slot (there's
            // no room), so surface the Drive attach button as a sibling so
            // users can still pull more items from Drive mid-draft.
            <div className="transfer-form__extra-sources">
              <DriveAttachButton
                onPick={handleFilesChange}
                onError={setFileError}
                disabled={busy}
                maxFileSize={config.TRANSFER_MAX_FILE_SIZE}
              />
            </div>
          )}

          {fileError && <Alert type={VariantType.ERROR}>{fileError}</Alert>}
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
                  ? t("Send {{count}} item", { count: files.length })
                  : t("Send")
                : t("Create link")}
          </Button>
        </section>
      </div>

      {busy && (
        <div
          className="transfer-form__busy-overlay"
          role="status"
          aria-live="polite"
        >
          <div className="transfer-form__busy-inner">
            {uploadProgress ? (
              <>
                {uploadProgress.fileCount > 1 && (
                  <p className="transfer-form__progress-sublabel">
                    {t("File {{current}} of {{total}}: {{name}}", {
                      current: uploadProgress.fileIndex + 1,
                      total: uploadProgress.fileCount,
                      name: uploadProgress.fileName,
                    })}
                  </p>
                )}
                <p className="transfer-form__progress-label">
                  {t("Uploading {{current}} / {{total}}", {
                    current: formatBytes(uploadProgress.totalLoaded),
                    total: formatBytes(uploadProgress.totalTotal),
                  })}
                </p>
                <div
                  className="transfer-form__progress-bar"
                  role="progressbar"
                  aria-valuenow={Math.round(
                    (uploadProgress.totalLoaded / uploadProgress.totalTotal) *
                      100,
                  )}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="transfer-form__progress-fill"
                    style={{
                      width: `${Math.round(
                        (uploadProgress.totalLoaded /
                          uploadProgress.totalTotal) *
                          100,
                      )}%`,
                    }}
                  />
                </div>
                <p className="transfer-form__progress-percent">
                  {Math.round(
                    (uploadProgress.totalLoaded / uploadProgress.totalTotal) *
                      100,
                  )}
                  %
                </p>
                <Button
                  type="button"
                  color="neutral"
                  size="small"
                  onClick={() => {
                    createTransfer.abort();
                  }}
                >
                  {t("Cancel")}
                </Button>
              </>
            ) : (
              <>
                <div
                  className="transfer-form__busy-spinner"
                  aria-hidden="true"
                />
                <p>{t("Sending...")}</p>
              </>
            )}
          </div>
        </div>
      )}

      {createTransfer.isError && (
        <Alert type={VariantType.ERROR}>{t("Error creating transfer.")}</Alert>
      )}
    </form>
  );
}
