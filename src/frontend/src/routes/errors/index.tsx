import { createFileRoute } from "@tanstack/react-router";

import { Error } from "@/features/errors/components/Error";
import { ErrorPageLayout } from "@/features/errors/components/ErrorPageLayout";

type ErrorContent = { title: string; message: string };

// Keyed by the ``reason`` the OIDC callback appends to /errors. An unknown or
// absent reason (a cancelled login, an expired state) falls back to a neutral
// message rather than claiming the service is missing from the user's offer.
const CONTENT_BY_REASON: Record<string, ErrorContent> = {
  access_denied: {
    title: "Accès refusé",
    message: "Ce service n'est pas inclus dans l'offre de votre opérateur.",
  },
  unavailable: {
    title: "Service momentanément indisponible",
    message:
      "La vérification de vos droits d'accès a échoué. Merci de réessayer dans quelques instants.",
  },
};

const DEFAULT_CONTENT: ErrorContent = {
  title: "La connexion a échoué",
  message: "Une erreur est survenue pendant la connexion. Merci de réessayer.",
};

const ErrorsPage = () => {
  const { reason } = Route.useSearch();
  const content =
    reason && Object.prototype.hasOwnProperty.call(CONTENT_BY_REASON, reason)
      ? CONTENT_BY_REASON[reason]
      : DEFAULT_CONTENT;
  return (
    <ErrorPageLayout>
      <Error title={content.title} message={content.message} />
    </ErrorPageLayout>
  );
};

export const Route = createFileRoute("/errors/")({
  validateSearch: (search: Record<string, unknown>) => ({
    reason: typeof search.reason === "string" ? search.reason : undefined,
  }),
  component: ErrorsPage,
});
