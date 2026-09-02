import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input } from "@gouvfr-lasuite/cunningham-react";
import { ArrowUpCircle, ArrowUpDown, Checkmark, Copy, WarningFilled } from "@gouvfr-lasuite/ui-kit/icons";
import type { TransferDetail } from "@/features/api/types";

export function TransferFailed({
  transfer,
  encryptionFragment,
  onNewTransfer,
  onGoToDetail,
}: {
  transfer: TransferDetail;
  // Confidential email-mode finalizes forward the key fragment here via the
  // navigation hash (same as TransferSuccess). This is the ONLY screen that
  // will ever show it: the detail page can't reconstruct it by design, so
  // dropping it here silently would lose the key for good even though the
  // link itself did reach some recipients. Null for non-confidential
  // transfers, or when the sender reached this URL without the hash
  // (refresh, bookmark).
  encryptionFragment: string | null;
  onNewTransfer: () => void;
  onGoToDetail: () => void;
}) {
  const { t } = useTranslation();
  const [keyCopied, setKeyCopied] = useState(false);
  const failedCount = transfer.recipients.filter(
    (r) => r.email_sent_at === null,
  ).length;
  const totalCount = transfer.recipients.length;

  const handleCopyKey = async () => {
    if (!encryptionFragment) return;
    try {
      await navigator.clipboard.writeText(encryptionFragment);
      setKeyCopied(true);
      setTimeout(() => setKeyCopied(false), 2000);
    } catch {
      // Clipboard may be unavailable on insecure contexts; swallow silently.
    }
  };

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

      {/* Mirror of TransferSuccess's key-share panel. The recipients who DID
          get the email hold a working link; the key still has to travel to
          them out-of-band, and the ones we'll retry from the summary page
          will need it too. Same strings as the success screen so the sender
          sees one consistent instruction whichever path they land on. */}
      {transfer.confidential && encryptionFragment && (
        <div className="transfer-failed__key-share">
          <p className="transfer-failed__body">
            {t(
              "This transfer is confidential: the email contains only the link. Send this decryption key to your recipients over a separate, trusted channel. We never received it and won't show it again.",
            )}
          </p>
          <div className="transfer-failed__link-box">
            <Input
              readOnly
              hideLabel
              label={t("Decryption key")}
              value={encryptionFragment}
              variant="classic"
              fullWidth
              onFocus={(e) => e.currentTarget.select()}
            />
            <Button
              type="button"
              size="small"
              color="neutral"
              variant="tertiary"
              icon={keyCopied ? <Checkmark /> : <Copy />}
              onClick={handleCopyKey}
              aria-label={keyCopied ? t("Key copied!") : t("Copy key")}
              title={keyCopied ? t("Key copied!") : t("Copy key")}
            />
          </div>
        </div>
      )}
      {transfer.confidential && !encryptionFragment && (
        <p className="transfer-failed__body">
          {t(
            "The decryption key isn't available on this device and can't be recovered. If you didn't copy it when you created the transfer, your recipients won't be able to open the files.",
          )}
        </p>
      )}

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
