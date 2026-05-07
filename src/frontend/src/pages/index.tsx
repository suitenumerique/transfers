import type { ReactElement } from "react";
import { useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main/MainLayout";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";
import { TransferForm } from "@/features/transfers/components/TransferForm";

import { Alert, VariantType } from "@gouvfr-lasuite/cunningham-react";

import type { NextPageWithLayout } from "./_app";

type EntitlementsPayload = {
  can_access?: { result?: boolean };
  can_upload?: { result?: boolean };
} | null;

type HomePageProps = {
  entitlements: EntitlementsPayload;
  entitlementsStatus: number | null;
};

function getApiOriginServerSide() {
  // Server-side: prefer a dedicated internal origin when provided.
  if (process.env.API_SERVER_ORIGIN) return process.env.API_SERVER_ORIGIN;

  const publicOrigin = process.env.NEXT_PUBLIC_API_ORIGIN;
  if (publicOrigin?.includes("localhost")) return "http://backend-dev:8000";

  return publicOrigin || "";
}

export async function getServerSideProps(ctx: {
  req: { headers: { cookie?: string } };
}) {
  const apiOrigin = getApiOriginServerSide();

  let entitlements: EntitlementsPayload = null;
  let entitlementsStatus: number | null = null;

  if (apiOrigin) {
    try {
      const apiEntitlements = await fetch(`${apiOrigin}/api/v1.0/entitlements/`, {
        headers: {
          cookie: ctx.req.headers.cookie ?? "",
        },
      });

      entitlementsStatus = apiEntitlements.status;
      if (apiEntitlements.ok) {
        entitlements = (await apiEntitlements.json()) as EntitlementsPayload;
      }
    } catch {
      entitlementsStatus = 0;
      entitlements = null;
    }
  }

  return {
    props: {
      entitlements,
      entitlementsStatus,
    } satisfies HomePageProps,
  };
}

const HomePage: NextPageWithLayout<HomePageProps> = ({
  entitlements,
  entitlementsStatus,
}) => {
  const { user } = useAuth();

  if (!user) {
    return <HomeLanding />;
  }

  const canAccess = entitlements?.can_access?.result === true;
  const canUpload = entitlements?.can_upload?.result === true;
  const canUseFormUpload = canAccess && canUpload;

  const hasEntitlements = entitlementsStatus === 200 && entitlements !== null;
  const entitlementsFailed = entitlementsStatus !== 200;

  return (
    <div className="app-content home">
      <div className="home__grid">
        <section className="home__upload">
          {entitlementsFailed && (
            <Alert type={VariantType.ERROR}>
              <div>
                <p>Impossible de récupérer vos habilitations.</p>
                <p>Merci de contacter <strong>Lysiane</strong> pour plus d'informations.</p>
              </div>
            </Alert>
          )}
          {hasEntitlements && canUseFormUpload && <TransferForm />}
          {hasEntitlements && !canUseFormUpload && (
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
