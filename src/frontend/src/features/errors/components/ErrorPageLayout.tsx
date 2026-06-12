import { type PropsWithChildren } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  LaGaufreV2,
  MainLayout as UIKitLayout,
} from "@gouvfr-lasuite/ui-kit";
import { TERRITORIALE_GAUFRE } from "@/features/config/constants";

export function ErrorPageLayout({ children }: PropsWithChildren) {
  const { t } = useTranslation();

  return (
    <UIKitLayout
      hideLeftPanelOnDesktop
      icon={
        <Link href="/" aria-label={t("Home")}>
          <img src="/images/transferts-logo.svg" alt="Transferts" height={40} />
        </Link>
      }
      rightHeaderContent={
        <LaGaufreV2
          widgetPath={TERRITORIALE_GAUFRE.widgetPath}
          apiUrl={TERRITORIALE_GAUFRE.apiUrl}
          showMoreLimit={100}
        />
      }
    >
      <section className="error-page">{children}</section>
    </UIKitLayout>
  );
}
