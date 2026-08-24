import { useTranslation } from "react-i18next";
import { UserMenu } from "@gouvfr-lasuite/ui-kit";
import { LeftPanel } from "@gouvfr-lasuite/ui-kit/icons";
import { useAuth, logout } from "@/features/auth";
import { Gaufre } from "@/features/layouts/components/gaufre";
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
        <LeftPanel />
      </button>
      <div className="shell-topbar__spacer" />
      <Gaufre />
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
