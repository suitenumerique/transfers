import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { usePublicDepositSpace } from "@/features/deposits/api/usePublicDepositSpace";
import { depositErrorMessage } from "@/features/deposits/components/depositErrors";
import { DepositWizard } from "@/features/deposits/components/DepositWizard";
import { PublicShell } from "@/features/deposits/components/PublicShell";

// A deposit space's public page: anyone with the link deposits files for
// the agent who shared it.
function DepositPage() {
  const { t } = useTranslation();
  const { token } = Route.useParams();
  const { data, isLoading, error } = usePublicDepositSpace(token);

  return (
    <PublicShell>
      {isLoading ? (
        <div className="download-page__status" aria-label={t("Loading...")}>
          <Spinner size="lg" />
        </div>
      ) : !data ? (
        <p className="download-page__status">{depositErrorMessage(error)}</p>
      ) : (
        <DepositWizard
          spaceToken={token}
          recipientLabel={
            data.owner_name ? `${data.name} (${data.owner_name})` : data.name
          }
          maxDepositSize={data.max_deposit_size}
          maxFiles={data.max_files}
        />
      )}
    </PublicShell>
  );
}

export const Route = createFileRoute("/d/$token")({
  component: DepositPage,
});
