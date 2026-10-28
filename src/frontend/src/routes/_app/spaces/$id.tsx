import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useDepositSpace } from "@/features/deposits/api/useDepositSpace";
import { SpaceDetail } from "@/features/deposits/components/SpaceDetail";

const SpaceRoute = () => {
  const { t } = useTranslation();
  const { id } = Route.useParams();
  const { data: space, isLoading, isError } = useDepositSpace(id);

  if (isLoading)
    return (
      <div className="app-content app-content--loading">
        <Spinner size="lg" />
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
