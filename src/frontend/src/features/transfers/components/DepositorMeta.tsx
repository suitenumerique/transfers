import { useTranslation } from "react-i18next";
import { Tooltip } from "@gouvfr-lasuite/cunningham-react";
import { Badge, Icon } from "@gouvfr-lasuite/ui-kit";
import { Checkmark, Warning } from "@gouvfr-lasuite/ui-kit/icons";

interface Depositor {
  depositor_name: string;
  depositor_email: string;
  depositor_verified: boolean;
}

// Who deposited a transfer, first in its meta line: their name (cut short;
// whole, with the address, on hover) and a badge saying whether their
// address was checked, why on hover.
export function DepositorMeta({
  transfer,
  className,
}: {
  transfer: Depositor;
  className: string;
}) {
  const { t } = useTranslation();
  const values = { email: transfer.depositor_email };
  return (
    <span className={className}>
      <Icon name="inbox" />
      <Tooltip
        content={`${transfer.depositor_name} (${transfer.depositor_email})`}
        placement="top"
      >
        <span className="depositor-meta__name">{transfer.depositor_name}</span>
      </Tooltip>
      <Tooltip
        content={
          transfer.depositor_verified
            ? t(
                "{{email}} was checked: the depositor entered a code sent to it, or signed in with ProConnect.",
                values,
              )
            : t(
                "{{email}} was typed by the depositor and never checked: this space does not ask for an email code. Anyone could have used this address.",
                values,
              )
        }
        placement="top"
      >
        <span className="depositor-meta__badge">
          {transfer.depositor_verified ? (
            <Badge type="success">
              <Checkmark />
              {t("Verified address")}
            </Badge>
          ) : (
            <Badge type="warning">
              <Warning />
              {t("Address not verified")}
            </Badge>
          )}
        </span>
      </Tooltip>
    </span>
  );
}
