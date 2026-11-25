import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Alert, Button, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { ApiError } from "@/features/api/client";
import { userFacingError } from "@/features/utils/user-facing-error";
import { useDepositSpace } from "@/features/deposits/api/useDepositSpace";
import { useAuth } from "@/features/auth";
import { SpaceDetail } from "@/features/deposits/components/SpaceDetail";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";

// Signed out (a member opening the email that shared the space): the
// landing, whose sign-in comes back here.
const SpaceRoute = () => {
  const { user } = useAuth();
  if (!user) return <HomeLanding />;
  return <SpacePage />;
};

const SpacePage = () => {
  const { t } = useTranslation();
  const { id } = Route.useParams();
  const { data: space, isLoading, isError, error, refetch } = useDepositSpace(id);

  if (isLoading)
    return (
      <div className="app-content app-content--loading">
        <Spinner size="lg" />
      </div>
    );
  if (isError && !(error instanceof ApiError && error.status === 404))
    return (
      <div className="app-content">
        <Alert type={VariantType.ERROR}>{userFacingError(error)}</Alert>
        <Button color="neutral" onClick={() => void refetch()}>
          {t("Retry")}
        </Button>
      </div>
    );
  if (isError || !space)
    return (
      <p className="app-content">{t("This deposit space does not exist.")}</p>
    );
  return (
    <div className="app-content">
      {/* Keyed so a rename re-seeds the form from the saved name. */}
      <SpaceDetail key={`${space.id}-${space.name}`} space={space} />
    </div>
  );
};

export const Route = createFileRoute("/_app/spaces/$id")({
  component: SpaceRoute,
});
