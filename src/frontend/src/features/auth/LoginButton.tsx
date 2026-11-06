import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ProConnectButton } from "@gouvfr-lasuite/ui-kit";

import { login } from "@/features/auth";
import { useTheme } from "@/features/theme";

export type LoginButtonProps = {
  size?: "small" | "medium";
};

/**
 * Sign-in affordance. Neutral by default; renders the ProConnect button only
 * where the operator declared ProConnect federation
 * (``theme.home["with-proconnect"]``, the key ``docs`` already uses). The
 * branded button carries the French State identity provider's mark, so it has
 * no business appearing on an instance that authenticates against some other
 * OIDC provider.
 */
export function LoginButton({ size }: LoginButtonProps = {}) {
  const { t } = useTranslation();
  const theme = useTheme();

  if (theme.home?.["with-proconnect"]) {
    return <ProConnectButton onClick={login} />;
  }

  return (
    <Button color="brand" size={size} onClick={login}>
      {t("Sign in")}
    </Button>
  );
}
