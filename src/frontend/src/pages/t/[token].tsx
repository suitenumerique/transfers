import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { ApiError } from "@/features/api/client";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { useDownloadTransfer } from "@/features/transfers/api/useDownload";
import { DownloadView } from "@/features/transfers/components/DownloadView";
import { PasswordPrompt } from "@/features/transfers/components/PasswordPrompt";
import {
  clearRecipientPassword,
  getRecipientPassword,
  saveRecipientPassword,
} from "@/features/transfers/utils/recipientPasswordStorage";

type DownloadErrorReason =
  | "expired"
  | "revoked"
  | "not_found"
  | "password_required"
  | "wrong_password";

function getErrorReason(error: unknown): DownloadErrorReason {
  if (error instanceof ApiError) {
    const body = error.body as { reason?: string } | undefined;
    if (
      body?.reason === "expired" ||
      body?.reason === "revoked" ||
      body?.reason === "not_found" ||
      body?.reason === "password_required" ||
      body?.reason === "wrong_password"
    ) {
      return body.reason;
    }
  }
  return "not_found";
}

export default function DownloadPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const token = router.query.token as string | undefined;
  // The candidate password is either typed by the recipient in the
  // PasswordPrompt or auto-loaded from localStorage on mount. It is sent on
  // every API call as a Bearer header; never leaves the device otherwise.
  const [password, setPassword] = useState<string | null>(null);
  // Whether the recipient asked us to remember the password on this device.
  // Only set to true when they explicitly opt in via the prompt checkbox, or
  // implicitly true when we pick up a password already in localStorage (meaning
  // they opted in on a previous visit).
  const [rememberOnDevice, setRememberOnDevice] = useState(false);

  useEffect(() => {
    if (!token) return;
    const existing = getRecipientPassword(token);
    if (existing) {
      setPassword(existing);
      setRememberOnDevice(true);
    }
  }, [token]);

  const handlePromptSubmit = (candidate: string, remember: boolean) => {
    setPassword(candidate);
    setRememberOnDevice(remember);
  };

  const { data, isLoading, isError, error, isFetching } = useDownloadTransfer(
    token,
    password,
  );

  // Persist the password the moment the backend accepts it — but only if
  // the recipient opted in.
  useEffect(() => {
    if (data && token && password && rememberOnDevice) {
      saveRecipientPassword(token, password);
    }
  }, [data, token, password, rememberOnDevice]);

  // Drop a persisted password as soon as the backend rejects it so we don't
  // keep re-sending a stale one on every refresh.
  useEffect(() => {
    if (!isError || !token) return;
    const reason = getErrorReason(error);
    if (reason === "wrong_password" || reason === "revoked" || reason === "expired") {
      clearRecipientPassword(token);
    }
  }, [isError, error, token]);

  const renderContent = () => {
    if (isLoading) {
      return <p>{t("Loading...")}</p>;
    }
    if (isError || !data) {
      const reason = getErrorReason(error);
      if (
        (reason === "password_required" || reason === "wrong_password") &&
        token
      ) {
        return (
          <PasswordPrompt
            wrongPassword={reason === "wrong_password"}
            pending={isFetching}
            onSubmit={handlePromptSubmit}
          />
        );
      }
      const messages: Record<
        Exclude<DownloadErrorReason, "password_required" | "wrong_password">,
        string
      > = {
        expired: t("This link has expired. Contact the sender."),
        revoked: t("This link has been revoked by the sender."),
        not_found: t("This link does not exist."),
      };
      return (
        <>
          <h1>{t("Transferts")}</h1>
          <p>
            {
              messages[
                reason as Exclude<
                  DownloadErrorReason,
                  "password_required" | "wrong_password"
                >
              ]
            }
          </p>
        </>
      );
    }
    return <DownloadView transfer={data} token={token!} password={password} />;
  };

  return (
    <div className="download-page">
      <header className="download-page__header">
        <LanguagePicker size="small" compact />
      </header>
      {renderContent()}
    </div>
  );
}
