import { useEffect, useState } from "react";
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
import { Icon, ProConnectButton } from "@gouvfr-lasuite/ui-kit";
import type { SharingMode } from "@/features/api/types";
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

const EXPIRY_CHOICES = [7, 30, 90];

function stripExtension(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

interface TransferFormProps {
  // When present, called before submitting if the user is not yet
  // authenticated. Must resolve once auth has been refreshed.
  requireAuth?: () => Promise<void>;
  // Notifies the parent page when the form enters/leaves the busy state
  // (auth in progress or transfer being created). Lets the page hide
  // sections that would flash in between the popup closing and the
  // route change.
  onBusyChange?: (busy: boolean) => void;
}

export function TransferForm({
  requireAuth,
  onBusyChange,
}: TransferFormProps = {}) {
  const { t, i18n } = useTranslation();
  const router = useRouter();
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
  const [passwordEnabled, setPasswordEnabled] = useState(false);
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [authing, setAuthing] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const handleFilesChange = (incoming: File[]) => {
    setFiles((prev) => {
      // De-duplicate on (name, size, lastModified) — same signature the browser
      // uses when you re-pick the same file; good enough for our purposes.
      const key = (f: File) => `${f.name}|${f.size}|${f.lastModified}`;
      const existing = new Set(prev.map(key));
      const merged = [
        ...prev,
        ...incoming.filter((f) => !existing.has(key(f))),
      ];
      return merged;
    });
    if (incoming.length > 0 && title.trim() === "") {
      setTitle(stripExtension(incoming[0].name));
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const submitTransfer = async () => {
    if (files.length === 0) return;
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
  };

  // `busy` stays true from the moment the user clicks submit until we have
  // navigated away to /transfers/{id}. It drives a full-viewport overlay that
  // hides the transitional state of the home (authenticated list appearing
  // under the form) between the popup closing and the route change.
  const busy = authing || createTransfer.isPending;

  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return;
    setAuthError(null);
    setPasswordError(null);

    if (sharingMode === "email" && recipients.length === 0) {
      return;
    }

    if (passwordEnabled && password.length < 8) {
      setPasswordError(t("Password must be at least 8 characters."));
      return;
    }

    if (requireAuth) {
      setAuthing(true);
      try {
        await requireAuth();
      } catch (err) {
        setAuthing(false);
        const reason = (err as Error).message;
        setAuthError(
          reason === "popup-blocked"
            ? t("Please allow popups to sign in.")
            : reason === "popup-timeout"
              ? t("Sign-in timed out.")
              : reason === "popup-closed"
                ? t("Sign-in cancelled. If the sign-in window is still open, please close it.")
                : t("Sign-in was cancelled."),
        );
        return;
      }
      // Keep authing=true through submit so the overlay stays visible until
      // the route change takes effect — otherwise the home re-renders the
      // authed state for a flash before navigation.
    }

    try {
      await submitTransfer();
    } catch {
      setAuthing(false);
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

        {requireAuth ? (
          <div className="transfer-form__proconnect">
            <p className="transfer-form__proconnect-lead">
              {t(
                "Sign in to create your transfer. The link will be generated right after.",
              )}
            </p>
            <ProConnectButton
              onClick={() => {
                void handleSubmit({
                  preventDefault: () => {},
                } as React.FormEvent);
              }}
              disabled={createTransfer.isPending || authing || !hasFiles}
            />
            {(authing || createTransfer.isPending) && (
              <span className="transfer-form__hint">
                {authing ? t("Signing in...") : t("Sending...")}
              </span>
            )}
          </div>
        ) : (
          <Button
            type="submit"
            disabled={createTransfer.isPending || !hasFiles || (sharingMode === "email" && recipients.length === 0)}
          >
            {createTransfer.isPending
              ? t("Sending...")
              : sharingMode === "email"
                ? t("Send")
                : t("Create link")}
          </Button>
        )}
      </div>

      {busy && (
        <div
          className="transfer-form__busy-overlay"
          role="status"
          aria-live="polite"
        >
          <div className="transfer-form__busy-inner">
            {authing ? (
              <>
                <div
                  className="transfer-form__busy-spinner"
                  aria-hidden="true"
                />
                <p>{t("Signing in...")}</p>
              </>
            ) : uploadProgress ? (
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

      {authError && <Alert type={VariantType.ERROR}>{authError}</Alert>}
      {createTransfer.isError && (
        <Alert type={VariantType.ERROR}>
          {t("Error creating transfer.")}
        </Alert>
      )}
    </form>
  );
}
