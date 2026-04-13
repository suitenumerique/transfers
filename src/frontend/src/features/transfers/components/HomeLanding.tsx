import { useTranslation } from "react-i18next";

export function HomeLanding() {
  const { t } = useTranslation();

  return (
    <aside className="home-landing">
      <img
        className="home-landing__logo"
        src="/images/transferts-logo.svg"
        alt="Transferts"
      />
      <h1 className="home-landing__title">
        {t("Sovereign file transfer service")}
      </h1>
      <p className="home-landing__subtitle">
        {t(
          "The sovereign file sharing service for French local government agents.",
        )}
      </p>
    </aside>
  );
}
