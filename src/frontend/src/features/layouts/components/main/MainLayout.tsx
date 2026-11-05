import { type PropsWithChildren } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { MainLayout as UIKitLayout } from "@gouvfr-lasuite/ui-kit";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { ShellLayout } from "@/features/layouts/components/shell";
import { Gaufre } from "../gaufre";
import { useAuth } from "@/features/auth";
import { LoginButton } from "@/features/auth/LoginButton";
import { ProductLogo } from "@/features/theme";

export function MainLayout({ children }: PropsWithChildren) {
  const { t } = useTranslation();
  const { user } = useAuth();

  // Authenticated users get the app shell (sidebar + minimal top bar).
  if (user) {
    return <ShellLayout>{children}</ShellLayout>;
  }

  // Unauthenticated: keep the UI Kit header-only layout for the landing page.
  return (
    <UIKitLayout
      hideLeftPanelOnDesktop
      icon={
        <Link to="/" aria-label={t("Home")}>
          <ProductLogo height={40} />
        </Link>
      }
      rightHeaderContent={
        <>
          <Gaufre />
          <LanguagePicker size="small" compact />
          {/* Same affordance as the landing: a deployment federated with
              ProConnect must not show its button in one place and a neutral
              one in the other. */}
          <LoginButton size="small" />
        </>
      }
    >
      {children}
    </UIKitLayout>
  );
}
