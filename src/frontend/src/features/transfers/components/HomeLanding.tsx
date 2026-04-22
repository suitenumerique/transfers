import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ArrowRight, ProConnectButton } from "@gouvfr-lasuite/ui-kit";
import { login } from "@/features/auth";

// Public landing, pre-login. Single centered column for now — the mock
// pairs it with an illustration on the right which isn't ready yet.
// Wire the right column back in once the asset lands.
const LEARN_MORE_URL = "https://suiteterritoriale.anct.gouv.fr/";

export function HomeLanding() {
  const { t } = useTranslation();

  return (
    <section className="home-landing">
      <div className="home-landing__content">
        <img
          className="home-landing__icon"
          src="/images/transferts-icon.svg"
          alt=""
          aria-hidden="true"
          width={48}
          height={48}
        />
        <h1 className="home-landing__title">
          {t("Send and receive in a snap")}
        </h1>
        <p className="home-landing__subtitle">
          {t(
            "The simple, fast, secure way to move your large files around.",
          )}
        </p>
        <div className="home-landing__actions">
          <ProConnectButton onClick={login} />
          <Button
            color="brand"
            variant="tertiary"
            iconPosition="right"
            icon={<ArrowRight />}
            href={LEARN_MORE_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("Learn more")}
          </Button>
        </div>
      </div>
    </section>
  );
}
