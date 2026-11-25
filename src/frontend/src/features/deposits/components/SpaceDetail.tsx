import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  Modal,
  ModalSize,
  useModal,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { UserAvatar } from "@gouvfr-lasuite/ui-kit";
import { Checkmark, Copy, XMark } from "@gouvfr-lasuite/ui-kit/icons";
import type { DepositSpace, DepositSpaceSettings } from "@/features/api/types";
import { keyCheck } from "@/features/transfers/upload/encryption";
import { useConfig } from "@/features/providers/config";
import { formatFullDateTime } from "@/features/utils/date";
import { isValidEmail } from "@/features/utils/email";
import { formatFileSize } from "@/features/utils/string-helper";
import { displayNameFromEmail } from "@/features/transfers/components/RecipientStatusList";
import { userFacingError } from "@/features/utils/user-facing-error";
import { useDeleteDepositSpace } from "../api/useDeleteDepositSpace";
import { useUpdateDepositSpace } from "../api/useUpdateDepositSpace";
import {
  dateInputValue,
  depositLink,
  recallSpaceKey,
  rememberSpaceKey,
  spaceIsOpen,
} from "../spaces";
import { DepositList } from "./DepositList";
import { SpaceOptions, type SpaceOptionValues } from "./SpaceOptions";

const optionsOf = (space: DepositSpace): SpaceOptionValues => ({
  retention_days: space.retention_days,
  expires_at: space.expires_at,
  single_use: space.single_use,
  verify_email: space.verify_email,
});

export function SpaceDetail({ space }: { space: DepositSpace }) {
  const { t, i18n } = useTranslation();
  const config = useConfig();
  const navigate = useNavigate();
  const update = useUpdateDepositSpace(space.id);
  const remove = useDeleteDepositSpace(space.id);
  const deleteModal = useModal();
  const [name, setName] = useState(space.name);
  const [options, setOptions] = useState(() => optionsOf(space));
  const [newMember, setNewMember] = useState("");
  const [memberTouched, setMemberTouched] = useState(false);
  const memberInvalid = newMember.trim() !== "" && !isValidEmail(newMember);
  const [copied, setCopied] = useState(false);
  const [key, setKey] = useState(() =>
    space.confidential ? recallSpaceKey(space.id) : null,
  );
  const [pastedLink, setPastedLink] = useState("");
  const [pasteError, setPasteError] = useState(false);
  const e2eOff = space.confidential && !config.TRANSFER_CONFIDENTIAL_ENABLED;
  const open = spaceIsOpen(space);
  // Nothing reopens these: a used single-use space, or an end-to-end one
  // while that mode is off. An expired one reopens with a later end date.
  const locked = Boolean(space.used_at) || e2eOff;
  const closedReason = () => {
    if (space.used_at) {
      return t(
        "This space is closed: it took its one deposit on {{date}}. Create a new space to receive more.",
        { date: formatFullDateTime(space.used_at, i18n.language) },
      );
    }
    if (e2eOff) {
      return t(
        "This space is closed: end-to-end encryption is turned off on this service.",
      );
    }
    if (space.expires_at && new Date(space.expires_at) <= new Date()) {
      return t(
        "This space has been closed since {{date}}. Push back the end date below to reopen it.",
        { date: formatFullDateTime(space.expires_at, i18n.language) },
      );
    }
    // Its owner's account was closed.
    return t("This space is closed: its link no longer accepts deposits.");
  };
  // An end-to-end link is only whole with its key.
  const link = space.confidential && !key ? null : depositLink(space, key);
  const saved = optionsOf(space);
  const dirty =
    name.trim() !== space.name ||
    options.retention_days !== saved.retention_days ||
    options.single_use !== saved.single_use ||
    options.verify_email !== saved.verify_email ||
    dateInputValue(options.expires_at) !== dateInputValue(saved.expires_at);

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable: the field below stays selectable.
    }
  };

  // Keep the full link of an end-to-end space in this browser, once its
  // key is checked against the one the space was made with.
  const restoreKey = async () => {
    const fragment = pastedLink.trim().split("#").pop() ?? "";
    if (fragment && (await keyCheck(fragment)) === space.key_check) {
      rememberSpaceKey(space.id, fragment);
      setKey(fragment);
      setPastedLink("");
    } else {
      setPasteError(true);
    }
  };

  const setMembers = (emails: string[]) =>
    update.mutate({ member_emails: emails });

  return (
    <div className="deposits">
      <h1 className="deposits__title">{space.name}</h1>
      {!open && <Alert type={VariantType.WARNING}>{closedReason()}</Alert>}
      {(open || !space.is_owner) && (
        <p className="deposits__intro">
          {open &&
            t(
              "Anyone with this link can send you up to {{size}} per deposit.",
              {
                size: formatFileSize(space.max_deposit_size),
              },
            )}
          {!space.is_owner &&
            ` ${t("Shared with you by {{email}}.", { email: space.owner_email })}`}
        </p>
      )}

      {space.confidential && (
        <Alert type={VariantType.INFO}>
          {t(
            "End-to-end space: only the full link, with its key, can encrypt and open deposits. We never received the key and cannot give it back.",
          )}
        </Alert>
      )}

      {open && link && (
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

      {space.confidential && !key && (
        <form
          className="deposits__create"
          onSubmit={(e) => {
            e.preventDefault();
            void restoreKey();
          }}
        >
          <Input
            label={t("Full deposit link")}
            variant="classic"
            value={pastedLink}
            onChange={(e) => {
              setPastedLink(e.currentTarget.value);
              setPasteError(false);
            }}
            state={pasteError ? "error" : "default"}
            text={
              pasteError
                ? t("This is not the link of this space.")
                : t(
                    "This browser does not have the key. Paste the full link to show it here and open the deposits.",
                  )
            }
          />
          <Button type="submit" color="neutral" disabled={!pastedLink.trim()}>
            {t("Use this link")}
          </Button>
        </form>
      )}

      {space.is_owner && (
        <h2 className="deposits__subtitle">{t("Settings")}</h2>
      )}
      {space.is_owner && (
        <form
          className="deposits__create-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!dirty || !name.trim()) return;
            // Only what the owner changed: an end date already past is
            // refused, and would block a mere rename.
            const changes: DepositSpaceSettings = {};
            if (name.trim() !== space.name) changes.name = name.trim();
            if (options.retention_days !== saved.retention_days)
              changes.retention_days = options.retention_days;
            if (options.single_use !== saved.single_use)
              changes.single_use = options.single_use;
            if (options.verify_email !== saved.verify_email)
              changes.verify_email = options.verify_email;
            if (
              dateInputValue(options.expires_at) !==
              dateInputValue(saved.expires_at)
            )
              changes.expires_at = options.expires_at;
            update.mutate(changes);
          }}
        >
          <Input
            label={t("Name")}
            variant="classic"
            fullWidth
            value={name}
            disabled={locked}
            onChange={(e) => setName(e.currentTarget.value)}
            maxLength={80}
          />
          <SpaceOptions
            values={options}
            onChange={setOptions}
            disabled={locked}
            hasDeposits={space.deposit_count > 0 && !space.used_at}
          />
          {!locked && (
            <div className="deposits__actions">
              <Button
                type="submit"
                color="neutral"
                disabled={!dirty || !name.trim() || update.isPending}
              >
                {t("Save")}
              </Button>
            </div>
          )}
        </form>
      )}
      {update.isError && (
        <Alert type={VariantType.ERROR}>{userFacingError(update.error)}</Alert>
      )}

      <h2 className="deposits__subtitle">{t("Shared with")}</h2>
      <p className="deposits__intro">
        {t(
          "Members see the deposits and download them, and are emailed at each one. They sign in with the address you give, even if they never used the service.",
        )}
      </p>
      <ul className="deposits__members">
        <li className="deposits__member">
          <UserAvatar
            fullName={displayNameFromEmail(space.owner_email)}
            size="small"
          />
          <span className="deposits__member-email">{space.owner_email}</span>
          <span className="deposits__member-role">{t("Owner")}</span>
        </li>
        {space.member_emails.map((email) => (
          <li key={email} className="deposits__member">
            <UserAvatar fullName={displayNameFromEmail(email)} size="small" />
            <span className="deposits__member-email">{email}</span>
            {space.is_owner && (
              <Button
                size="small"
                color="neutral"
                variant="tertiary"
                icon={<XMark />}
                disabled={update.isPending}
                aria-label={t("Remove {{email}}", { email })}
                title={t("Remove {{email}}", { email })}
                onClick={() =>
                  setMembers(space.member_emails.filter((e) => e !== email))
                }
              />
            )}
          </li>
        ))}
      </ul>
      {space.member_emails.length === 0 && (
        <p className="deposits__empty">{t("Nobody else yet.")}</p>
      )}
      {space.is_owner && (
        <form
          className="deposits__create"
          onSubmit={(e) => {
            e.preventDefault();
            const email = newMember.trim().toLowerCase();
            if (!email || memberInvalid) return;
            update.mutate(
              { member_emails: [...space.member_emails, email] },
              {
                onSuccess: () => {
                  setNewMember("");
                  setMemberTouched(false);
                },
              },
            );
          }}
        >
          <Input
            label={t("Email address of the person to add")}
            variant="classic"
            type="email"
            value={newMember}
            onChange={(e) => setNewMember(e.currentTarget.value)}
            onBlur={() => setMemberTouched(true)}
            state={memberTouched && memberInvalid ? "error" : "default"}
            text={
              memberTouched && memberInvalid
                ? t("Invalid email address.")
                : undefined
            }
          />
          <Button
            type="submit"
            color="neutral"
            disabled={!newMember.trim() || memberInvalid || update.isPending}
          >
            {t("Share")}
          </Button>
        </form>
      )}

      <h2 className="deposits__subtitle">{t("Deposits received")}</h2>
      <DepositList spaceId={space.id} />

      {space.is_owner && (
        <div className="deposits__danger">
          <Button
            type="button"
            color="error"
            variant="secondary"
            onClick={deleteModal.open}
          >
            {t("Delete the space")}
          </Button>
        </div>
      )}

      <Modal
        size={ModalSize.SMALL}
        isOpen={deleteModal.isOpen}
        onClose={() => {
          remove.reset();
          deleteModal.close();
        }}
        title={t("Delete this space?")}
        rightActions={
          <>
            <Button
              color="neutral"
              variant="secondary"
              onClick={deleteModal.close}
            >
              {t("Cancel")}
            </Button>
            <Button
              color="error"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(undefined, {
                  onSuccess: () => {
                    deleteModal.close();
                    void navigate({ to: "/spaces" });
                  },
                })
              }
            >
              {t("Delete the space")}
            </Button>
          </>
        }
      >
        {remove.isError && (
          <Alert type={VariantType.ERROR}>
            {userFacingError(remove.error)}
          </Alert>
        )}
        {t(
          "The link stops working, and the space's {{count}} deposit is deleted with its files. This is irreversible.",
          { count: space.deposit_count },
        )}
      </Modal>
    </div>
  );
}
