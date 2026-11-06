import type { PropsWithChildren } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { QuestionMark } from "@gouvfr-lasuite/ui-kit/icons";
import { Gaufre } from "@/features/layouts/components/gaufre";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { useConfig } from "@/features/providers/config";

// The chrome of the pages people without an account use to deposit files:
// the download page's, without its sign-in button.
export function PublicShell({ children }: PropsWithChildren) {
  const { t } = useTranslation();
  const config = useConfig();
  return (
    <div className="download-page">
      <header className="download-page__topbar">
        <Link
          to="/"
          className="download-page__brand"
          aria-label={t("Transferts")}
        >
          <img src="/images/transfers-logo.svg" alt="Transferts" height={36} />
        </Link>
        <div className="download-page__topbar-right">
          <LanguagePicker size="small" compact />
          <Gaufre />
        </div>
      </header>
      <main className="download-page__main">{children}</main>
      {config.HELP_URL && (
        <Button
          color="neutral"
          variant="tertiary"
          size="small"
          icon={<QuestionMark />}
          aria-label={t("Help")}
          title={t("Help")}
          href={config.HELP_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="download-page__help"
        />
      )}
    </div>
  );
}
