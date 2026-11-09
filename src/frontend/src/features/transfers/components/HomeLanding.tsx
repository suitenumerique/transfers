import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ProConnectButton } from "@gouvfr-lasuite/ui-kit";
import { ArrowRight } from "@gouvfr-lasuite/ui-kit/icons";
import { login } from "@/features/auth";
import { useConfig } from "@/features/providers/config";

// Public landing, pre-login. Single centered column for now — the mock
// pairs it with an illustration on the right which isn't ready yet.
// Wire the right column back in once the asset lands.
const LEARN_MORE_URL = "https://suiteterritoriale.anct.gouv.fr/";

export function HomeLanding() {
  const { t } = useTranslation();
  const config = useConfig();

  return (
    <section className="home-landing">
      <div className="home-landing__content">
        <img
          className="home-landing__icon"
          src="/images/transfers-icon.svg"
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
        {config.INBOX_ENABLED && (
          <div className="home-landing__send">
            <h2 className="home-landing__send-title">{t("No account?")}</h2>
            <p className="home-landing__subtitle">
              {t("Send files to a public agent, no sign-in needed.")}
            </p>
            <Button
              color="brand"
              variant="secondary"
              iconPosition="right"
              icon={<ArrowRight />}
              href="/send"
            >
              {t("Send files")}
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}
