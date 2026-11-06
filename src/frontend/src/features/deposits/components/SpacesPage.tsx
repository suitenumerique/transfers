import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  Select,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useConfig } from "@/features/providers/config";
import { userFacingError } from "@/features/utils/user-facing-error";
import { useCreateDepositSpace } from "../api/useCreateDepositSpace";
import { useDepositSpaces } from "../api/useDepositSpaces";
import { useRetentionOptions } from "../api/useRetentionOptions";

// An agent's deposit spaces: links people without an account use to send
// them files.
export function SpacesPage() {
  const { t } = useTranslation();
  const config = useConfig();
  const retentionOptions = useRetentionOptions();
  const spaces = useDepositSpaces();
  const create = useCreateDepositSpace();
  const [name, setName] = useState("");
  const [retention, setRetention] = useState(
    config.DEPOSIT_SPACE_DEFAULT_RETENTION_DAYS,
  );

  const submit = () => {
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), retention_days: retention },
      { onSuccess: () => setName("") },
    );
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
        className="deposits__create"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Input
          label={t("New space name")}
          value={name}
          onChange={(e) => {
            if (create.isError) create.reset();
            setName(e.currentTarget.value);
          }}
          maxLength={80}
        />
        <Select
          label={t("Deposits kept")}
          options={retentionOptions}
          value={String(retention)}
          clearable={false}
          onChange={(e) => setRetention(Number(e.target.value))}
        />
        <Button
          type="submit"
          color="brand"
          disabled={!name.trim() || create.isPending}
        >
          {t("Create")}
        </Button>
      </form>
      {create.isError && (
        <Alert type={VariantType.ERROR}>{userFacingError(create.error)}</Alert>
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
                  {space.revoked_at && ` · ${t("Closed")}`}
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
