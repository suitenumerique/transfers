import { Mail } from "@gouvfr-lasuite/ui-kit";

const SUPPORT_LINK_URL =
  "https://docs.suite.anct.gouv.fr/docs/281bc1f0-5911-4442-b4b7-af78d77f0e1e/";

export type ErrorProps = {
  title: string;
  message: string;
};

export function Error({ title, message }: ErrorProps) {
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
      <a
        className="service-error__support"
        href={SUPPORT_LINK_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Mail aria-hidden="true" />
        Contacter le support
      </a>
    </div>
  );
}
