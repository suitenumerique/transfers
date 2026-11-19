import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { usePublicDepositSpace } from "@/features/deposits/api/usePublicDepositSpace";
import { depositErrorMessage } from "@/features/deposits/components/depositErrors";
import { DepositWizard } from "@/features/deposits/components/DepositWizard";
import { PublicShell } from "@/features/deposits/components/PublicShell";
import { keyCheck } from "@/features/transfers/upload/encryption";

// A deposit space's public page: anyone with the link deposits files for
// the agent who shared it.
function DepositPage() {
  const { t } = useTranslation();
  const { token } = Route.useParams();
  const { data, isLoading, error } = usePublicDepositSpace(token);
  // An end-to-end space's key rides in the fragment, never sent to us.
  const [fragment] = useState(() => window.location.hash.replace(/^#/, ""));
  const [fragmentCheck, setFragmentCheck] = useState<string | null>(null);
  useEffect(() => {
    if (fragment) void keyCheck(fragment).then(setFragmentCheck);
  }, [fragment]);
  // null while the check runs.
  const keyOk = !fragment
    ? false
    : fragmentCheck === null
      ? null
      : fragmentCheck === data?.key_check;

  return (
    <PublicShell>
      {isLoading ? (
        <div className="download-page__status" aria-label={t("Loading...")}>
          <Spinner size="lg" />
        </div>
      ) : !data ? (
        <p className="download-page__status">{depositErrorMessage(error)}</p>
      ) : data.confidential && keyOk === null ? (
        <div className="download-page__status" aria-label={t("Loading...")}>
          <Spinner size="lg" />
        </div>
      ) : data.confidential && !keyOk ? (
        <p className="download-page__status">
          {t(
            "This link is incomplete: its end of the address is missing or damaged. Ask the person who sent it for the full link.",
          )}
        </p>
      ) : (
        <DepositWizard
          spaceToken={token}
          recipientLabel={
            data.owner_name ? `${data.name} (${data.owner_name})` : data.name
          }
          maxDepositSize={data.max_deposit_size}
          maxFiles={data.max_files}
          verifyEmail={data.verify_email}
          presetKey={data.confidential ? fragment : undefined}
        />
      )}
    </PublicShell>
  );
}

export const Route = createFileRoute("/d/$token")({
  component: DepositPage,
});
