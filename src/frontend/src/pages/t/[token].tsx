import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { ApiError } from "@/features/api/client";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { useDownloadTransfer } from "@/features/transfers/api/useDownload";
import { DownloadView } from "@/features/transfers/components/DownloadView";

type DownloadErrorReason = "expired" | "revoked" | "not_found";

function getErrorReason(error: unknown): DownloadErrorReason {
  if (error instanceof ApiError) {
    const body = error.body as { reason?: string } | undefined;
    if (
      body?.reason === "expired" ||
      body?.reason === "revoked" ||
      body?.reason === "not_found"
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

  const { data, isLoading, isError, error } = useDownloadTransfer(token);

  const renderContent = () => {
    if (isLoading) {
      return <p>{t("Loading...")}</p>;
    }
    if (isError || !data) {
      const reason = getErrorReason(error);
      const messages: Record<DownloadErrorReason, string> = {
        expired: t("This link has expired. Contact the sender."),
        revoked: t("This link has been revoked by the sender."),
        not_found: t("This link does not exist."),
      };
      return (
        <>
          <h1>{t("Transferts")}</h1>
          <p>{messages[reason]}</p>
        </>
      );
    }
    return <DownloadView transfer={data} token={token!} />;
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
