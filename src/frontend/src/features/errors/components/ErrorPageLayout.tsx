import { type PropsWithChildren } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { MainLayout as UIKitLayout } from "@gouvfr-lasuite/ui-kit";
import { Gaufre } from "@/features/layouts/components/gaufre";

export function ErrorPageLayout({ children }: PropsWithChildren) {
  const { t } = useTranslation();

  return (
    <UIKitLayout
      hideLeftPanelOnDesktop
      icon={
        <Link to="/" aria-label={t("Home")}>
          <img src="/images/transferts-logo.svg" alt="Transferts" height={40} />
        </Link>
      }
      rightHeaderContent={<Gaufre />}
    >
      <section className="error-page">{children}</section>
    </UIKitLayout>
  );
}
