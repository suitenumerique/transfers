import { type PropsWithChildren } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { MainLayout as UIKitLayout } from "@gouvfr-lasuite/ui-kit";
import { Gaufre } from "@/features/layouts/components/gaufre";
import { ProductLogo } from "@/features/theme";

export function ErrorPageLayout({ children }: PropsWithChildren) {
  const { t } = useTranslation();

  return (
    <UIKitLayout
      hideLeftPanelOnDesktop
      icon={
        <Link to="/" aria-label={t("Home")}>
          <ProductLogo height={40} />
        </Link>
      }
      rightHeaderContent={<Gaufre />}
    >
      <section className="error-page">{children}</section>
    </UIKitLayout>
  );
}
