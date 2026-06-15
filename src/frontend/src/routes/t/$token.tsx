import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { LaGaufreV2, ProConnectButton, Spinner } from "@gouvfr-lasuite/ui-kit";
import { QuestionMark } from "@gouvfr-lasuite/ui-kit/icons";
import { ApiError } from "@/features/api/client";
import { login, useAuth } from "@/features/auth";
import { TERRITORIALE_GAUFRE } from "@/features/config/constants";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { useConfig } from "@/features/providers/config";
import { useDownloadTransfer } from "@/features/transfers/api/useDownload";
import { DownloadView } from "@/features/transfers/components/DownloadView";

type DownloadErrorReason = "expired" | "deactivated" | "not_found";

function getErrorReason(error: unknown): DownloadErrorReason {
  if (error instanceof ApiError) {
    const body = error.body as { reason?: string } | undefined;
    if (
      body?.reason === "expired" ||
      body?.reason === "deactivated" ||
      body?.reason === "not_found"
    ) {
      return body.reason;
    }
  }
  return "not_found";
}

function DownloadPage() {
  const { t } = useTranslation();
  const { token } = Route.useParams();
  const config = useConfig();
  const { user } = useAuth();

  const { data, isLoading, isError, error } = useDownloadTransfer(token);

  const renderContent = () => {
    if (isLoading) {
      return (
        <div className="download-page__status" aria-label={t("Loading...")}>
          <Spinner size="lg" />
        </div>
      );
    }
    if (isError || !data) {
      const reason = getErrorReason(error);
      const messages: Record<DownloadErrorReason, string> = {
        expired: t("This link has expired. Contact the sender."),
        deactivated: t("This link has been deactivated by the sender."),
        not_found: t("This link does not exist."),
      };
      return (
        <p className="download-page__status">{messages[reason]}</p>
      );
    }
    return <DownloadView transfer={data} token={token!} isOwner={user?.email?.toLowerCase() === data.owner_email?.toLowerCase()} />;
  };

  return (
    <div className="download-page">
      <header className="download-page__topbar">
        <Link
          to="/"
          className="download-page__brand"
          aria-label={t("Transferts")}
        >
          {/* The bundled "transferts-logo.svg" is the wordmark — icon +
              "Transferts" text already inside the SVG. Don't double up
              with a sibling label or you get two "Transferts" strings. */}
          <img
            src="/images/transferts-logo.svg"
            alt="Transferts"
            height={36}
          />
        </Link>
        <div className="download-page__topbar-right">
          <LanguagePicker size="small" compact />
          <LaGaufreV2
            widgetPath={TERRITORIALE_GAUFRE.widgetPath}
            apiUrl={TERRITORIALE_GAUFRE.apiUrl}
            showMoreLimit={100}
          />
          {!user && <ProConnectButton onClick={login} />}
        </div>
      </header>

      <main className="download-page__main">{renderContent()}</main>

      {config.HELP_URL && (
        <Button
          color="neutral"
          variant="tertiary"
          size="small"
          icon={<QuestionMark />}
          aria-label={t("Help")}
          title={t("Help")}
          href={config.HELP_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="download-page__help"
        />
      )}
    </div>
  );
}

export const Route = createFileRoute("/t/$token")({
  component: DownloadPage,
});
