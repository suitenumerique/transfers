import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Alert, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { ApiError } from "@/features/api/client";
import { login, useAuth } from "@/features/auth";
import { claimInbound, rememberPendingClaim } from "../api/claimInbound";

// Opened from the email of an anonymous send: attach it to the signed-in
// agent, signing them in first if needed.
export function InboxClaim({ token }: { token: string }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current || !token) return;
    started.current = true;
    if (!user) {
      rememberPendingClaim(token);
      login();
      return;
    }
    claimInbound(token)
      .then(async ({ id }) => {
        // The inbox lists the sends just collected.
        await queryClient.invalidateQueries({ queryKey: ["transfers"] });
        await navigate({ to: "/transfers/$id", params: { id }, replace: true });
      })
      .catch((err) => {
        const reason =
          err instanceof ApiError
            ? (err.body as { reason?: string } | undefined)?.reason
            : undefined;
        setError(
          reason === "wrong_account"
            ? t(
                "These files were sent to another address. Sign in with the account of the address that received the email.",
              )
            : reason === "expired"
              ? t("This deposit has expired.")
              : reason === "not_found"
                ? t("These files were already collected by another account.")
                : t("This link is not valid."),
        );
      });
  }, [token, user, navigate, queryClient, t]);

  if (!token) {
    return (
      <Alert type={VariantType.ERROR}>{t("This link is not valid.")}</Alert>
    );
  }
  if (error) {
    return <Alert type={VariantType.ERROR}>{error}</Alert>;
  }
  return <Spinner size="lg" />;
}
