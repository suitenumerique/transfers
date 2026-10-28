import { createFileRoute } from "@tanstack/react-router";
import { useAuth } from "@/features/auth";
import { SpacesPage } from "@/features/deposits/components/SpacesPage";
import { HomeLanding } from "@/features/transfers/components/HomeLanding";

const SpacesRoute = () => {
  const { user } = useAuth();
  if (!user) return <HomeLanding />;
  return (
    <div className="app-content">
      <SpacesPage />
    </div>
  );
};

export const Route = createFileRoute("/_app/spaces/")({
  component: SpacesRoute,
});
