import type { ReactElement } from "react";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/features/api/client";
import { useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferForm } from "@/features/transfers/components/TransferForm";

import { Alert, VariantType } from "@gouvfr-lasuite/cunningham-react";

import type { NextPageWithLayout } from "./_app";

const HomePage: NextPageWithLayout = () => {
  const { user } = useAuth();

  if (!user) {
    return <HomeLanding />;
  }

  type EntitlementsPayload = Record<string, unknown>;
  const fetchEntitlements = () => apiFetch<EntitlementsPayload>("/entitlements/");

  const entitlementsQuery = useQuery<EntitlementsPayload>({
    queryKey: ["entitlements"],
    queryFn: fetchEntitlements,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (entitlementsQuery.data) {
      // eslint-disable-next-line no-console
      console.log("[entitlements]", entitlementsQuery.data);
    }
  }, [entitlementsQuery.data]);

  useEffect(() => {
    if (entitlementsQuery.error) {
      // eslint-disable-next-line no-console
      console.error("[entitlements] failed", entitlementsQuery.error);
    }
  }, [entitlementsQuery.error]);

  const data = entitlementsQuery.data as
    | {
        can_access?: { result?: boolean };
        can_upload?: { result?: boolean };
      }
    | undefined;

  const canAccess = data?.can_access?.result === true;
  const canUpload = data?.can_upload?.result === true;
  const canUseFormUpload = canAccess && canUpload;

  return (
    <div className="app-content home">
      <div className="home__grid">
        <section className="home__upload">
          {entitlementsQuery.isError && (
            <Alert type={VariantType.ERROR}>
              <div>
                <p>Impossible de récupérer vos habilitations.</p>
                <p>Merci de contacter <strong>Lysiane</strong> pour plus d'informations.</p>
              </div>
            </Alert>
          )}
          {entitlementsQuery.isSuccess && canUseFormUpload && <TransferForm />}
          {entitlementsQuery.isSuccess && !canUseFormUpload && (
            <Alert type={VariantType.ERROR}>
              <div>
                <p>Vous n'avez pas les permissions nécessaires pour uploader des fichiers.</p>
                <p>Merci de contacter <strong>Lysiane</strong> pour plus d'informations.</p>
              </div>
            </Alert>
          )}
        </section>
      </div>
    </div>
  );
};

HomePage.getLayout = (page: ReactElement) => {
  return <MainLayout>{page}</MainLayout>;
};

export default HomePage;
