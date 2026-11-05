import { Mail } from "@gouvfr-lasuite/ui-kit/icons";
import { useTranslation } from "react-i18next";

import { useSupportUrl } from "@/features/theme";

export type ErrorProps = {
  title: string;
  message: string;
};

export function Error({ title, message }: ErrorProps) {
  const { t } = useTranslation();
  const supportUrl = useSupportUrl();
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
      {supportUrl && (
        <a
          className="service-error__support"
          href={supportUrl}
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
