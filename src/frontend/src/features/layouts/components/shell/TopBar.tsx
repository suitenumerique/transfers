import { useTranslation } from "react-i18next";
import { IconLeftPanel, LaGaufreV2, UserMenu } from "@gouvfr-lasuite/ui-kit";
import { useAuth, logout } from "@/features/auth";
import { TERRITORIALE_GAUFRE } from "@/features/config/constants";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";

interface TopBarProps {
  sidebarCollapsed: boolean;
  onToggle: () => void;
}

export function TopBar({ sidebarCollapsed, onToggle }: TopBarProps) {
  const { t } = useTranslation();
  const { user } = useAuth();

  return (
    <header className="shell-topbar">
      <button
        type="button"
        className="shell-topbar__icon-btn"
        onClick={onToggle}
        aria-label={sidebarCollapsed ? t("Open sidebar") : t("Collapse sidebar")}
        title={sidebarCollapsed ? t("Open sidebar") : t("Collapse sidebar")}
      >
        <IconLeftPanel />
      </button>
      <div className="shell-topbar__spacer" />
      <LaGaufreV2
        widgetPath={TERRITORIALE_GAUFRE.widgetPath}
        apiUrl={TERRITORIALE_GAUFRE.apiUrl}
        showMoreLimit={100}
      />
      {user && (
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
      )}
    </header>
  );
}
