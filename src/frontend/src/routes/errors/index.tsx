import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Error } from "@/features/errors/components/Error";
import { ErrorPageLayout } from "@/features/errors/components/ErrorPageLayout";

type ErrorContent = { title: string; message: string };

// Keyed by the ``reason`` the OIDC callback appends to /errors. An unknown or
// absent reason (a cancelled login, an expired state) falls back to a neutral
// message rather than claiming the service is missing from the user's offer.
// Values are translation keys, resolved through ``t`` at render time.
const CONTENT_BY_REASON: Record<string, ErrorContent> = {
  access_denied: {
    title: "Access denied",
    message: "This service is not included in your operator's offer.",
  },
  unavailable: {
    title: "Service temporarily unavailable",
    message:
      "We could not verify your access rights. Please try again in a moment.",
  },
};

const DEFAULT_CONTENT: ErrorContent = {
  title: "Sign-in failed",
  message: "Something went wrong while signing you in. Please try again.",
};

const ErrorsPage = () => {
  const { t } = useTranslation();
  const { reason } = Route.useSearch();
  const content =
    reason && Object.prototype.hasOwnProperty.call(CONTENT_BY_REASON, reason)
      ? CONTENT_BY_REASON[reason]
      : DEFAULT_CONTENT;
  return (
    <ErrorPageLayout>
      <Error title={t(content.title)} message={t(content.message)} />
    </ErrorPageLayout>
  );
};

export const Route = createFileRoute("/errors/")({
  validateSearch: (search: Record<string, unknown>) => ({
    reason: typeof search.reason === "string" ? search.reason : undefined,
  }),
  component: ErrorsPage,
});
