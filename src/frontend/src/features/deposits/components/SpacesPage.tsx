import { useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useConfig } from "@/features/providers/config";
import {
  generateTransferKey,
  keyCheck,
} from "@/features/transfers/upload/encryption";
import { userFacingError } from "@/features/utils/user-facing-error";
import { useCreateDepositSpace } from "../api/useCreateDepositSpace";
import { useDepositSpaces } from "../api/useDepositSpaces";
import { spaceIsOpen } from "../spaces";
import { SpaceOptions, type SpaceOptionValues } from "./SpaceOptions";

// An agent's deposit spaces, their own and those shared with them: links
// people without an account use to send them files.
export function SpacesPage() {
  const { t } = useTranslation();
  const config = useConfig();
  const navigate = useNavigate();
  const spaces = useDepositSpaces();
  const create = useCreateDepositSpace();
  const [name, setName] = useState("");
  const [options, setOptions] = useState<SpaceOptionValues>({
    retention_days: config.DEPOSIT_SPACE_DEFAULT_RETENTION_DAYS,
    expires_at: null,
    single_use: false,
    verify_email: true,
  });
  const [confidential, setConfidential] = useState(false);
  const [keyError, setKeyError] = useState(false);
  // Taken before the key is made: a second click must not start another.
  const submittingRef = useRef(false);

  const submit = async () => {
    if (!name.trim() || create.isPending || submittingRef.current) return;
    submittingRef.current = true;
    setKeyError(false);
    try {
      // End-to-end: the key is made here and only its hash is sent.
      let key: string | null = null;
      let check = "";
      if (confidential) {
        try {
          key = (await generateTransferKey()).fragment;
          check = await keyCheck(key);
        } catch {
          setKeyError(true);
          return;
        }
      }
      await create
        .mutateAsync(
          { name: name.trim(), ...options, confidential, key_check: check, key },
          {
            onSuccess: (space) => {
              setName("");
              void navigate({ to: "/spaces/$id", params: { id: space.id } });
            },
          },
        )
        .catch(() => {
          // Shown by create.isError below.
        });
    } finally {
      submittingRef.current = false;
    }
  };

  return (
    <div className="deposits">
      <h1 className="deposits__title">{t("Deposit spaces")}</h1>
      <p className="deposits__intro">
        {t(
          "Share a space's link with people who don't have an account: they send you files through it, and you are emailed at each deposit.",
        )}
      </p>

      <form
        className="deposits__create-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="deposits__create">
          <Input
            label={t("New space name")}
            variant="classic"
            value={name}
            onChange={(e) => {
              if (create.isError) create.reset();
              setName(e.currentTarget.value);
            }}
            maxLength={80}
          />
          <Button
            type="submit"
            color="brand"
            disabled={!name.trim() || create.isPending}
          >
            {t("Create")}
          </Button>
        </div>
        <SpaceOptions values={options} onChange={setOptions} />
        {config.TRANSFER_CONFIDENTIAL_ENABLED && (
          <Checkbox
            label={t("End-to-end encryption")}
            text={t(
              "Files are encrypted with a key that only the link carries: we cannot read them, and the antivirus cannot check them. Keep the link: without it, deposits cannot be opened.",
            )}
            checked={confidential}
            onChange={(e) => setConfidential(e.currentTarget.checked)}
          />
        )}
      </form>
      {create.isError && (
        <Alert type={VariantType.ERROR}>{userFacingError(create.error)}</Alert>
      )}
      {keyError && (
        <Alert type={VariantType.ERROR}>
          {t("This browser could not make the encryption key. Try again.")}
        </Alert>
      )}

      {spaces.isLoading ? (
        <Spinner />
      ) : spaces.isError ? (
        <Alert type={VariantType.ERROR}>{userFacingError(spaces.error)}</Alert>
      ) : spaces.data && spaces.data.results.length > 0 ? (
        <ul className="deposits__list">
          {spaces.data.results.map((space) => (
            <li key={space.id} className="deposits__row">
              <Link
                to="/spaces/$id"
                params={{ id: space.id }}
                className="deposits__row-link"
              >
                <span className="deposits__row-title">{space.name}</span>
                <span className="deposits__row-meta">
                  {t("{{count}} deposit", { count: space.deposit_count })}
                  {!spaceIsOpen(space) && ` · ${t("Closed")}`}
                  {!space.is_owner &&
                    ` · ${t("Shared by {{email}}", { email: space.owner_email })}`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="deposits__empty">{t("No deposit space yet.")}</p>
      )}
    </div>
  );
}
