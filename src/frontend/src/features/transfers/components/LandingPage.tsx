import {
  Hero,
  HomeGutter,
  LaGaufreV2,
  MainLayout as UIKitLayout,
  ProConnectButton,
} from "@gouvfr-lasuite/ui-kit";
import { TERRITORIALE_GAUFRE } from "@/features/config/constants";
import { useTranslation } from "react-i18next";
import { LANGUAGES } from "@/features/i18n/conf";
import { handle } from "@/features/utils/errors";

interface LandingPageProps {
  onLogin: () => void;
}

// NOTE: placeholder — la vraie landing viendra de la designeuse.
export function LandingPage({ onLogin }: LandingPageProps) {
  const { t, i18n } = useTranslation();

  const languages = LANGUAGES.map((language: [string, string]) => ({
    value: language[0],
    label: language[1],
    isChecked: i18n.language === language[0],
    callback: () => {
      i18n.changeLanguage(language[0]).catch((error) => {
        handle(new Error("Error changing language."), {
          extra: { error, value: language[0] },
        });
      });
    },
  }));

  return (
    <UIKitLayout
      hideLeftPanelOnDesktop
      icon={
        <img src="/images/transferts-logo.svg" alt="Transferts" height={40} />
      }
      languages={languages}
      rightHeaderContent={
        <LaGaufreV2
          widgetPath={TERRITORIALE_GAUFRE.widgetPath}
          apiUrl={TERRITORIALE_GAUFRE.apiUrl}
          showMoreLimit={100}
        />
      }
    >
      <HomeGutter>
        <Hero
          logo={
            <img
              src="/images/transferts-icon.svg"
              alt="Transferts"
              width={72}
            />
          }
          title={t("Send your files, simply and securely.")}
          banner="/images/banner.webp"
          subtitle={t(
            "Transferts is the sovereign file sharing service for public agents of La Suite territoriale.",
          )}
          mainButton={<ProConnectButton onClick={onLogin} />}
        />
      </HomeGutter>
    </UIKitLayout>
  );
}
