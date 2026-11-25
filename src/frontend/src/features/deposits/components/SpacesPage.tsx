import { useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { Plus } from "@gouvfr-lasuite/ui-kit/icons";
import { useConfig } from "@/features/providers/config";
import {
  generateTransferKey,
  keyCheck,
} from "@/features/transfers/upload/encryption";
import { userFacingError } from "@/features/utils/user-facing-error";
import { useCreateDepositSpace } from "../api/useCreateDepositSpace";
import { SpaceOptions, type SpaceOptionValues } from "./SpaceOptions";

// A new deposit space: a link people without an account use to send the
// agent files. The spaces themselves are listed in the sidebar.
export function SpacesPage() {
  const { t } = useTranslation();
  const config = useConfig();
  const navigate = useNavigate();
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
      <h1 className="deposits__title">{t("New deposit space")}</h1>
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
        <Input
          label={t("Name")}
          variant="classic"
          fullWidth
          value={name}
          onChange={(e) => {
            if (create.isError) create.reset();
            setName(e.currentTarget.value);
          }}
          maxLength={80}
        />
        <SpaceOptions
          values={options}
          onChange={setOptions}
          advancedCount={Number(confidential)}
          advanced={
            config.TRANSFER_CONFIDENTIAL_ENABLED && (
              <Checkbox
                label={t("Confidential deposit space")}
                text={t(
                  "Recommended for sensitive data. The decryption key stays in the link and never reaches our servers: anyone with the full link can open the files.",
                )}
                checked={confidential}
                onChange={(e) => setConfidential(e.currentTarget.checked)}
              />
            )
          }
        />
        {create.isError && (
          <Alert type={VariantType.ERROR}>
            {userFacingError(create.error)}
          </Alert>
        )}
        {keyError && (
          <Alert type={VariantType.ERROR}>
            {t("This browser could not make the encryption key. Try again.")}
          </Alert>
        )}
        <Button
          type="submit"
          fullWidth
          icon={<Plus />}
          disabled={!name.trim() || create.isPending}
        >
          {t("Create")}
        </Button>
      </form>
    </div>
  );
}
