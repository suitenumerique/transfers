import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  Modal,
  ModalSize,
  Select,
  useModal,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { Checkmark, Copy } from "@gouvfr-lasuite/ui-kit/icons";
import type { DepositSpace } from "@/features/api/types";
import { formatFileSize } from "@/features/utils/string-helper";
import { userFacingError } from "@/features/utils/user-facing-error";
import { useRevokeDepositSpace } from "../api/useRevokeDepositSpace";
import { useRetentionOptions } from "../api/useRetentionOptions";
import { useUpdateDepositSpace } from "../api/useUpdateDepositSpace";
import { DepositList } from "./DepositList";

export function depositLink(space: DepositSpace): string {
  return `${window.location.origin}/d/${space.link_token}`;
}

export function SpaceDetail({ space }: { space: DepositSpace }) {
  const { t } = useTranslation();
  const retentionOptions = useRetentionOptions();
  const update = useUpdateDepositSpace(space.id);
  const revoke = useRevokeDepositSpace(space.id);
  const revokeModal = useModal();
  const [name, setName] = useState(space.name);
  const [copied, setCopied] = useState(false);
  const open = space.revoked_at === null;
  const link = depositLink(space);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable: the field below stays selectable.
    }
  };

  return (
    <div className="deposits">
      <h1 className="deposits__title">{space.name}</h1>
      <p className="deposits__intro">
        {open
          ? t(
              "Anyone with this link can send you up to {{size}} per deposit.",
              {
                size: formatFileSize(space.max_deposit_size),
              },
            )
          : t("This space is closed: its link no longer accepts deposits.")}
      </p>

      {open && (
        <div className="transfer-detail__link-box">
          <Input
            readOnly
            hideLabel
            label={t("Deposit link")}
            value={link}
            variant="classic"
            fullWidth
            onFocus={(e) => e.currentTarget.select()}
          />
          <Button
            size="small"
            color="neutral"
            variant="tertiary"
            icon={copied ? <Checkmark /> : <Copy />}
            onClick={() => void copy()}
            aria-label={copied ? t("Link copied!") : t("Copy link")}
            title={copied ? t("Link copied!") : t("Copy link")}
          />
        </div>
      )}

      {open && (
        <form
          className="deposits__create"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && name.trim() !== space.name) {
              update.mutate({ name: name.trim() });
            }
          }}
        >
          <Input
            label={t("Name")}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            maxLength={80}
          />
          <Select
            label={t("Deposits kept")}
            options={retentionOptions}
            value={String(space.retention_days)}
            clearable={false}
            onChange={(e) =>
              update.mutate({ retention_days: Number(e.target.value) })
            }
          />
          <Button
            type="submit"
            color="neutral"
            disabled={
              !name.trim() || name.trim() === space.name || update.isPending
            }
          >
            {t("Rename")}
          </Button>
          <Button
            type="button"
            color="error"
            variant="secondary"
            onClick={revokeModal.open}
          >
            {t("Close the space")}
          </Button>
        </form>
      )}
      {update.isError && (
        <Alert type={VariantType.ERROR}>{userFacingError(update.error)}</Alert>
      )}

      <h2 className="deposits__subtitle">{t("Deposits received")}</h2>
      <DepositList spaceId={space.id} />

      <Modal
        size={ModalSize.SMALL}
        isOpen={revokeModal.isOpen}
        onClose={revokeModal.close}
        title={t("Close this space?")}
        rightActions={
          <>
            <Button
              color="neutral"
              variant="secondary"
              onClick={revokeModal.close}
            >
              {t("Cancel")}
            </Button>
            <Button
              color="error"
              disabled={revoke.isPending}
              onClick={() =>
                revoke.mutate(undefined, { onSuccess: revokeModal.close })
              }
            >
              {t("Close the space")}
            </Button>
          </>
        }
      >
        {revoke.isError && (
          <Alert type={VariantType.ERROR}>
            {userFacingError(revoke.error)}
          </Alert>
        )}
        {t(
          "The link will stop accepting deposits, for good. Deposits already received stay until they expire.",
        )}
      </Modal>
    </div>
  );
}
