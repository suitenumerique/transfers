import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import {
  ArrowUpCircle,
  ArrowUpDown,
  WarningFilled,
} from "@gouvfr-lasuite/ui-kit";
import type { TransferDetail } from "@/features/api/types";

export function TransferFailed({
  transfer,
  onNewTransfer,
  onGoToDetail,
}: {
  transfer: TransferDetail;
  onNewTransfer: () => void;
  onGoToDetail: () => void;
}) {
  const { t } = useTranslation();
  const failedCount = transfer.recipients.filter(
    (r) => r.email_sent_at === null,
  ).length;
  const totalCount = transfer.recipients.length;

  return (
    <div className="transfer-failed" role="status">
      <div className="transfer-failed__icon" aria-hidden="true">
        <WarningFilled />
      </div>
      <h1 className="transfer-failed__title">
        {t("Some emails couldn't be sent")}
      </h1>
      <p className="transfer-failed__body">
        {t(
          "{{failed}} out of {{total}} recipients did not receive the notification email. Open the transfer summary to retry.",
          { failed: failedCount, total: totalCount },
        )}
      </p>

      <div className="transfer-failed__actions">
        <Button
          color="neutral"
          variant="tertiary"
          icon={<ArrowUpDown />}
          onClick={onNewTransfer}
        >
          {t("Start new transfer")}
        </Button>
        <Button color="brand" icon={<ArrowUpCircle />} onClick={onGoToDetail}>
          {t("View summary")}
        </Button>
      </div>
    </div>
  );
}
