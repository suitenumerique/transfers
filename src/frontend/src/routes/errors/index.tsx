import { createFileRoute } from "@tanstack/react-router";

import { Error } from "@/features/errors/components/Error";
import { ErrorPageLayout } from "@/features/errors/components/ErrorPageLayout";

const ACCESS_DENIED_TITLE = "Accès refusé";
const SERVICE_NOT_INCLUDED_MESSAGE =
  "Ce service n'est pas inclus dans l'offre de votre opérateur.";

const ErrorsPage = () => (
  <ErrorPageLayout>
    <Error title={ACCESS_DENIED_TITLE} message={SERVICE_NOT_INCLUDED_MESSAGE} />
  </ErrorPageLayout>
);

export const Route = createFileRoute("/errors/")({
  component: ErrorsPage,
});
