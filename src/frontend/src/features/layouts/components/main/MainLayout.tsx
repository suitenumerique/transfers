import { type PropsWithChildren } from "react";
import {
  LaGaufreV2,
  MainLayout as UIKitLayout,
  UserMenu,
} from "@gouvfr-lasuite/ui-kit";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { TERRITORIALE_GAUFRE } from "@/features/config/constants";
import { useAuth, logout } from "@/features/auth";

export function MainLayout({ children }: PropsWithChildren) {
  const { user } = useAuth();

  return (
    <UIKitLayout
      hideLeftPanelOnDesktop
      icon={
        <img src="/images/transferts-logo.svg" alt="Transferts" height={40} />
      }
      rightHeaderContent={
        <>
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
            <LanguagePicker size="small" compact />
          )}
        </>
      }
    >
      {children}
    </UIKitLayout>
  );
}
