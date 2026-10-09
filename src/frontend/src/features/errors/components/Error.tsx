import { Mail } from "@gouvfr-lasuite/ui-kit/icons";
import { useTranslation } from "react-i18next";

import { useConfig } from "@/features/providers/config";

export type ErrorProps = {
  title: string;
  message: string;
};

export function Error({ title, message }: ErrorProps) {
  const { t } = useTranslation();
  const config = useConfig();
  return (
    <div className="service-error" role="alert">
      <img
        className="service-error__illustration"
        src="/images/main-error.svg"
        alt=""
        aria-hidden="true"
        width={102}
        height={76}
      />
      <p className="service-error__title">{title}</p>
      <p className="service-error__message">{message}</p>
      {config.SUPPORT_URL && (
        <a
          className="service-error__support"
          href={config.SUPPORT_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Mail aria-hidden="true" />
          {t("Contact support")}
        </a>
      )}
    </div>
  );
}
