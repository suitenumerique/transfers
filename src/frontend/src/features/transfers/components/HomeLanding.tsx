import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ArrowRight } from "@gouvfr-lasuite/ui-kit/icons";
import { LoginButton } from "@/features/auth/LoginButton";
import { useConfig } from "@/features/providers/config";

// Public landing, pre-login. Single centered column for now — the mock
// pairs it with an illustration on the right which isn't ready yet.
// Wire the right column back in once the asset lands.

export function HomeLanding() {
  const { t } = useTranslation();
  const { FRONTEND_LEARN_MORE_URL: learnMoreUrl } = useConfig();

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
          <LoginButton />
          {learnMoreUrl && (
            <Button
              color="brand"
              variant="tertiary"
              iconPosition="right"
              icon={<ArrowRight />}
              href={learnMoreUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("Learn more")}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
