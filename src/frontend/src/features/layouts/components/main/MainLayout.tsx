import { type PropsWithChildren } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { LaGaufreV2, MainLayout as UIKitLayout } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { ShellLayout } from "@/features/layouts/components/shell";
import { TERRITORIALE_GAUFRE } from "@/features/config/constants";
import { useAuth, login } from "@/features/auth";

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
          <img src="/images/transferts-logo.svg" alt="Transferts" height={40} />
        </Link>
      }
      rightHeaderContent={
        <>
          <LaGaufreV2
            widgetPath={TERRITORIALE_GAUFRE.widgetPath}
            apiUrl={TERRITORIALE_GAUFRE.apiUrl}
            showMoreLimit={100}
          />
          <LanguagePicker size="small" compact />
          <Button size="small" onClick={login}>
            {t("Sign in")}
          </Button>
        </>
      }
    >
      {children}
    </UIKitLayout>
  );
}
