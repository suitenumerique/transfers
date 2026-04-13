import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  Select,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { ProConnectButton } from "@gouvfr-lasuite/ui-kit";
import { useCreateTransfer } from "../api/useCreateTransfer";
import { FileDropZone } from "./FileDropZone";

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
  const { t } = useTranslation();
  const router = useRouter();
  const createTransfer = useCreateTransfer();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<number>(30);
  const [authing, setAuthing] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const handleFilesChange = (files: File[]) => {
    const next = files.length > 0 ? files[0] : null;
    setFile(next);
    if (next && title.trim() === "") {
      setTitle(stripExtension(next.name));
    }
  };

  const submitTransfer = async () => {
    if (!file) return;
    const created = await createTransfer.mutateAsync({
      title,
      expires_in_days: expiresInDays,
      file,
    });
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
    if (!file) return;
    setAuthError(null);

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
    }
  };

  const expiryOptions = EXPIRY_CHOICES.map((days) => ({
    label: t("{{count}} days", { count: days }),
    value: String(days),
  }));

  return (
    <form onSubmit={handleSubmit} className="transfer-form">
      <FileDropZone
        files={file ? [file] : []}
        onChange={handleFilesChange}
        maxFiles={1}
      />

      <div
        className="transfer-form__reveal"
        data-visible={file ? "true" : undefined}
        aria-hidden={!file}
        aria-live="polite"
      >
        <Input
          label={t("Title")}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("My transfer")}
          disabled={!file}
          fullWidth
        />

        <Select
          label={t("Expiration")}
          options={expiryOptions}
          value={String(expiresInDays)}
          onChange={(e) => setExpiresInDays(Number(e.target.value))}
          disabled={!file}
          clearable={false}
          fullWidth
        />

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
              disabled={createTransfer.isPending || authing || !file}
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
            disabled={createTransfer.isPending || !file}
          >
            {createTransfer.isPending ? t("Sending...") : t("Create link")}
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
            <div className="transfer-form__busy-spinner" aria-hidden="true" />
            <p>
              {authing
                ? t("Signing in...")
                : createTransfer.isPending
                  ? t("Sending...")
                  : ""}
            </p>
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
