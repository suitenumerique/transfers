import { useTranslation } from "react-i18next";
import {
  Checkbox,
  DatePicker,
  Select,
} from "@gouvfr-lasuite/cunningham-react";
import { useRetentionOptions } from "../api/useRetentionOptions";
import { dateInputValue, endOfDayIso } from "../spaces";

export interface SpaceOptionValues {
  retention_days: number;
  expires_at: string | null;
  single_use: boolean;
  verify_email: boolean;
}

// The settings a space's owner can change at any time.
export function SpaceOptions({
  values,
  onChange,
  disabled,
}: {
  values: SpaceOptionValues;
  onChange: (values: SpaceOptionValues) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const retentionOptions = useRetentionOptions();
  const set = (patch: Partial<SpaceOptionValues>) =>
    onChange({ ...values, ...patch });
  // The earliest end date is today: the link then closes tonight.
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return (
    <div className="deposits__options">
      <Select
        label={t("Deposits kept")}
        variant="classic"
        fullWidth
        options={retentionOptions}
        value={String(values.retention_days)}
        clearable={false}
        disabled={disabled}
        onChange={(e) => set({ retention_days: Number(e.target.value) })}
      />
      <DatePicker
        label={t("Link open until")}
        variant="classic"
        fullWidth
        minValue={today.toISOString()}
        value={values.expires_at}
        disabled={disabled}
        text={t("Leave empty to keep the link open.")}
        // The picker gives the day's start; the link closes at its end.
        onChange={(value) =>
          set({ expires_at: value ? endOfDayIso(dateInputValue(value)) : null })
        }
      />
      <Checkbox
        label={t("Close the link after the first deposit")}
        checked={values.single_use}
        disabled={disabled}
        onChange={(e) => set({ single_use: e.currentTarget.checked })}
      />
      <Checkbox
        label={t("Check the depositor's email with a code")}
        text={t(
          "Adds an email verification step to confirm the user's identity.",
        )}
        checked={values.verify_email}
        disabled={disabled}
        onChange={(e) => set({ verify_email: e.currentTarget.checked })}
      />
    </div>
  );
}
