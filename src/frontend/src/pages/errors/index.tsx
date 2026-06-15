import { Error } from "@/features/errors/components/Error";
import { ErrorPageLayout } from "@/features/errors/components/ErrorPageLayout";

const ACCESS_DENIED_TITLE = "Accès refusé";
const SERVICE_NOT_INCLUDED_MESSAGE =
  "Ce service n'est pas inclus dans l'offre de votre opérateur.";

export default function ErrorsPage() {
  return (
    <ErrorPageLayout>
      <Error
        title={ACCESS_DENIED_TITLE}
        message={SERVICE_NOT_INCLUDED_MESSAGE}
      />
    </ErrorPageLayout>
  );
}
