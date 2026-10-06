import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ProConnectButton } from "@gouvfr-lasuite/ui-kit";

import { login } from "@/features/auth";
import { useOptionalConfig } from "@/features/providers/config";

/**
 * Sign-in affordance. Neutral by default; renders the ProConnect button only
 * where the operator declared ProConnect federation
 * (``FRONTEND_PROCONNECT_BUTTON``). The branded button carries the French
 * State identity provider's mark, so it has no business appearing on an
 * instance that authenticates against some other OIDC provider.
 */
export function LoginButton() {
  const { t } = useTranslation();
  const config = useOptionalConfig();

  if (config?.FRONTEND_PROCONNECT_BUTTON) {
    return <ProConnectButton onClick={login} />;
  }

  return (
    <Button color="brand" onClick={login}>
      {t("Sign in")}
    </Button>
  );
}
