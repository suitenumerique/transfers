import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { ArrowRight } from "@gouvfr-lasuite/ui-kit/icons";
import { LoginButton } from "@/features/auth/LoginButton";
import { ProductIcon, useTheme } from "@/features/theme";

// Public landing, pre-login. Single centered column for now — the mock
// pairs it with an illustration on the right which isn't ready yet.
// Wire the right column back in once the asset lands.

export function HomeLanding() {
  const { t } = useTranslation();
  const theme = useTheme();
  const learnMoreUrl = theme.home?.learn_more_url;
  // ``home["icon-banner"]`` is the key ``docs`` already uses for this slot.
  // Decorative unless the operator gives it a label: the heading right below
  // says the same thing, and a screen reader would otherwise hear it twice.
  const banner = theme.home?.["icon-banner"];

  return (
    <section className="home-landing">
      <div className="home-landing__content">
        {banner?.src ? (
          <img
            className="home-landing__icon"
            src={banner.src}
            alt={banner.alt ?? ""}
            aria-hidden={banner.alt ? undefined : true}
            width={banner.width}
            height={banner.height ?? 48}
            style={banner.style}
          />
        ) : (
          <ProductIcon
            className="home-landing__icon"
            height={banner?.height ?? 48}
            title={banner?.alt ?? ""}
          />
        )}
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
