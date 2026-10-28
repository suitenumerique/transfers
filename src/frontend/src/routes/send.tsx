import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { DepositWizard } from "@/features/deposits/components/DepositWizard";
import { PublicShell } from "@/features/deposits/components/PublicShell";
import { useConfig } from "@/features/providers/config";

// Send files straight to an agent's address, without an account, where the
// instance allows it.
function SendPage() {
  const { t } = useTranslation();
  const config = useConfig();
  return (
    <PublicShell>
      {config.INBOX_ENABLED ? (
        <DepositWizard
          spaceToken={null}
          maxDepositSize={config.DEPOSIT_MAX_TOTAL_SIZE}
          maxFiles={config.TRANSFER_MAX_FILES_PER_TRANSFER}
          retentionDays={config.INBOX_RETENTION_DAYS}
        />
      ) : (
        <p className="download-page__status">
          {t("Sending files without an account is not available here.")}
        </p>
      )}
    </PublicShell>
  );
}

export const Route = createFileRoute("/send")({
  component: SendPage,
});
