import { type PropsWithChildren } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import {
  LaGaufreV2,
  MainLayout as UIKitLayout,
  UserMenu,
} from "@gouvfr-lasuite/ui-kit";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { TERRITORIALE_GAUFRE } from "@/features/config/constants";
import { useAuth, login, logout } from "@/features/auth";

export function MainLayout({ children }: PropsWithChildren) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const router = useRouter();
  const onTransfersPage = router.pathname.startsWith("/transfers");

  return (
    <UIKitLayout
      hideLeftPanelOnDesktop
      icon={
        <Link href="/" aria-label={t("Home")}>
          <img src="/images/transferts-logo.svg" alt="Transferts" height={40} />
        </Link>
      }
      rightHeaderContent={
        <>
          {user && (
            <Link
              href="/transfers"
              className={`main-layout__nav-link${
                onTransfersPage ? " main-layout__nav-link--active" : ""
              }`}
            >
              {t("My transfers")}
            </Link>
          )}
          <LaGaufreV2
            widgetPath={TERRITORIALE_GAUFRE.widgetPath}
            apiUrl={TERRITORIALE_GAUFRE.apiUrl}
            showMoreLimit={100}
          />
          {user ? (
            <UserMenu
              user={{
                full_name: user.full_name ?? undefined,
                email: user.email ?? "",
              }}
              logout={logout}
              actions={
                <div className="user-menu__footer-action">
                  <LanguagePicker size="small" compact />
                </div>
              }
            />
          ) : (
            <>
              <LanguagePicker size="small" compact />
              <Button size="small" onClick={login}>
                {t("Sign in")}
              </Button>
            </>
          )}
        </>
      }
    >
      {children}
    </UIKitLayout>
  );
}
