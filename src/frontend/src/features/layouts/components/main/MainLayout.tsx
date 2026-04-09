import { type PropsWithChildren } from "react";
import Link from "next/link";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";
import { useAuth, logout } from "@/features/auth";

export function MainLayout({ children }: PropsWithChildren) {
  const { t } = useTranslation();
  const { user } = useAuth();

  return (
    <div className="main-layout">
      <header className="main-layout__header">
        <Link href="/" className="main-layout__logo">
          {t("Transferts")}
        </Link>
        <nav className="main-layout__nav">
          {user && (
            <>
              <Link href="/transfers/new">
                <Button size="small">{t("New transfer")}</Button>
              </Link>
              <span className="main-layout__user">
                {user.full_name || user.email}
              </span>
              <Button size="small" color="neutral" onClick={logout}>
                {t("Logout")}
              </Button>
            </>
          )}
        </nav>
      </header>
      <main className="main-layout__content">{children}</main>
    </div>
  );
}
