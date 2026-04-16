import { useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  Select,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import type { SharingMode } from "@/features/api/types";
import { useConfig } from "@/features/providers/config";
import {
  useCreateTransfer,
  type AggregateProgress,
} from "../api/useCreateTransfer";
import { generatePassphrase } from "../utils/generatePassword";
import { stashPassword } from "../utils/passwordStash";
import { FileDropZone } from "./FileDropZone";
import { RecipientInput } from "./RecipientInput";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function UsageBar({ currentSize, maxSize }: { currentSize: number; maxSize: number }) {
  const pct = Math.min((currentSize / maxSize) * 100, 100);
  const level = pct >= 90 ? "danger" : pct >= 70 ? "warning" : "ok";

  return (
    <div className="transfer-form__usage">
      <div className="transfer-form__usage-bar">
        <div
          className={`transfer-form__usage-fill transfer-form__usage-fill--${level}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="transfer-form__usage-label">
        {formatBytes(currentSize)} / {formatBytes(maxSize)}
      </span>
    </div>
  );
}

const EXPIRY_CHOICES = [7, 30, 90];

function stripExtension(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

export function TransferForm() {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const config = useConfig();
  const [uploadProgress, setUploadProgress] = useState<AggregateProgress | null>(
    null,
  );
  const createTransfer = useCreateTransfer({
    onProgress: (progress) => setUploadProgress(progress),
  });
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<number>(30);
  const [sharingMode, setSharingMode] = useState<SharingMode>("link");
  const [recipients, setRecipients] = useState<string[]>([]);
  const [hasValidPending, setHasValidPending] = useState(false);
  const [passwordEnabled, setPasswordEnabled] = useState(false);
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const handleFilesChange = (incoming: File[]) => {
    setFileError(null);

    // Reject individual files that exceed the per-file limit
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

      // Check file count limit
      if (merged.length > config.TRANSFER_MAX_FILES_PER_TRANSFER) {
        setFileError(
          t("Too many files. Maximum: {{max}}.", {
            max: config.TRANSFER_MAX_FILES_PER_TRANSFER,
          }),
        );
        return prev;
      }

      // Check total size limit
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return;
    setPasswordError(null);

    if (sharingMode === "email" && recipients.length === 0 && !hasValidPending) {
      return;
    }

    if (passwordEnabled && password.length < 8) {
      setPasswordError(t("Password must be at least 8 characters."));
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
      const passwordToSend = passwordEnabled ? password : undefined;
      const created = await createTransfer.mutateAsync({
        title,
        expires_in_days: expiresInDays,
        files,
        password: passwordToSend,
        sharing_mode: sharingMode,
        recipients: sharingMode === "email" ? recipients : undefined,
      });
      if (passwordToSend) stashPassword(created.id, passwordToSend);
      await router.push(`/transfers/${created.id}`);
    } catch {
      setUploadProgress(null);
    }
  };

  const expiryOptions = EXPIRY_CHOICES.map((days) => ({
    label: t("{{count}} days", { count: days }),
    value: String(days),
  }));

  const hasFiles = files.length > 0;

  return (
    <form onSubmit={handleSubmit} className="transfer-form">
      <FileDropZone files={files} onChange={handleFilesChange} />

      {hasFiles && (
        <>
          <ul className="transfer-form__file-list" aria-label={t("Selected files")}>
            {files.map((f, i) => (
              <li key={`${f.name}-${f.size}-${f.lastModified}`} className="transfer-form__file-item">
                <span className="transfer-form__file-name">{f.name}</span>
                <span className="transfer-form__file-size">{formatBytes(f.size)}</span>
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
          <UsageBar
            currentSize={files.reduce((sum, f) => sum + f.size, 0)}
            maxSize={config.TRANSFER_MAX_TOTAL_SIZE}
          />
        </>
      )}

      {fileError && (
        <Alert type={VariantType.ERROR}>{fileError}</Alert>
      )}

      <div
        className="transfer-form__reveal"
        data-visible={hasFiles ? "true" : undefined}
        aria-hidden={!hasFiles}
        aria-live="polite"
      >
        <Input
          label={t("Title")}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("My transfer")}
          disabled={!hasFiles}
          fullWidth
        />

        <fieldset className="transfer-form__sharing-toggle" disabled={!hasFiles}>
          <legend className="transfer-form__sharing-legend">
            {t("Sharing mode")}
          </legend>
          <div className="transfer-form__sharing-buttons">
            <button
              type="button"
              className={`transfer-form__sharing-btn${sharingMode === "link" ? " transfer-form__sharing-btn--active" : ""}`}
              onClick={() => {
                setSharingMode("link");
                setRecipients([]);
              }}
            >
              {t("Link")}
            </button>
            <button
              type="button"
              className={`transfer-form__sharing-btn${sharingMode === "email" ? " transfer-form__sharing-btn--active" : ""}`}
              onClick={() => setSharingMode("email")}
            >
              {t("Email")}
            </button>
          </div>
        </fieldset>

        {sharingMode === "email" && (
          <RecipientInput
            recipients={recipients}
            onChange={setRecipients}
            onPendingChange={setHasValidPending}
            disabled={!hasFiles || busy}
          />
        )}

        <Select
          label={t("Expiration")}
          options={expiryOptions}
          value={String(expiresInDays)}
          onChange={(e) => setExpiresInDays(Number(e.target.value))}
          disabled={!hasFiles}
          clearable={false}
          fullWidth
        />

        <Checkbox
          label={t("Protect with password")}
          checked={passwordEnabled}
          onChange={(e) => {
            const checked = (e.target as HTMLInputElement).checked;
            setPasswordEnabled(checked);
            if (!checked) {
              setPassword("");
              setPasswordError(null);
            }
          }}
          disabled={!hasFiles}
        />

        {passwordEnabled && (
          <Input
            label={t("Password")}
            type={passwordVisible ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={!hasFiles}
            state={passwordError ? "error" : "default"}
            text={passwordError ?? undefined}
            fullWidth
            rightIcon={
              <div className="transfer-form__password-actions">
                <button
                  type="button"
                  className="transfer-form__password-action"
                  onClick={() => setPasswordVisible((v) => !v)}
                  disabled={!hasFiles}
                  aria-label={passwordVisible ? t("Hide") : t("Show")}
                  aria-pressed={passwordVisible}
                >
                  <Icon
                    name={passwordVisible ? "visibility_off" : "visibility"}
                  />
                </button>
                <button
                  type="button"
                  className="transfer-form__password-action"
                  onClick={() => {
                    setPassword(generatePassphrase(i18n.language));
                    setPasswordError(null);
                    setPasswordVisible(true);
                  }}
                  disabled={!hasFiles}
                  aria-label={t("Generate")}
                  title={t("Generate")}
                >
                  <Icon name="auto_awesome" />
                </button>
              </div>
            }
          />
        )}

        <Button
          type="submit"
          disabled={busy || !hasFiles || (sharingMode === "email" && recipients.length === 0 && !hasValidPending)}
        >
          {busy
            ? t("Sending...")
            : sharingMode === "email"
              ? t("Send")
              : t("Create link")}
        </Button>
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
        <Alert type={VariantType.ERROR}>
          {t("Error creating transfer.")}
        </Alert>
      )}
    </form>
  );
}
