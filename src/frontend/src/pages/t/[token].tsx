import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { ApiError } from "@/features/api/client";
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
  // The candidate password is either the one typed by the recipient in the
  // PasswordPrompt or one loaded from localStorage on mount. It is sent on
  // every API call as a Bearer header; never leaves the device otherwise.
  const [password, setPassword] = useState<string | null>(null);
  useEffect(() => {
    if (token) setPassword(getRecipientPassword(token));
  }, [token]);

  const { data, isLoading, isError, error, isFetching } = useDownloadTransfer(
    token,
    password,
  );

  // Persist a password the moment the backend accepts it.
  useEffect(() => {
    if (data && token && password) saveRecipientPassword(token, password);
  }, [data, token, password]);

  // Drop a persisted password as soon as the backend rejects it so we don't
  // keep re-sending a stale one on every refresh.
  useEffect(() => {
    if (!isError || !token) return;
    const reason = getErrorReason(error);
    if (reason === "wrong_password" || reason === "revoked" || reason === "expired") {
      clearRecipientPassword(token);
    }
  }, [isError, error, token]);

  if (isLoading) {
    return (
      <div className="download-page">
        <p>{t("Loading...")}</p>
      </div>
    );
  }

  if (isError || !data) {
    const reason = getErrorReason(error);
    if (
      (reason === "password_required" || reason === "wrong_password") &&
      token
    ) {
      return (
        <div className="download-page">
          <PasswordPrompt
            wrongPassword={reason === "wrong_password"}
            pending={isFetching}
            onSubmit={setPassword}
          />
        </div>
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
      <div className="download-page">
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
      </div>
    );
  }

  return (
    <div className="download-page">
      <DownloadView transfer={data} token={token!} password={password} />
    </div>
  );
}
