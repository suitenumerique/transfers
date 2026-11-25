import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox, DatePicker, Select } from "@gouvfr-lasuite/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useRetentionOptions } from "../api/useRetentionOptions";
import { dateInputValue, endOfDayIso } from "../spaces";

export interface SpaceOptionValues {
  retention_days: number;
  expires_at: string | null;
  single_use: boolean;
  verify_email: boolean;
}

// The settings a space's owner can change at any time. ``advanced`` adds
// options of the caller's to the fold, ``advancedCount`` of them active.
// ``hasDeposits``: single use then closes on the next deposit, not the first.
export function SpaceOptions({
  values,
  onChange,
  disabled,
  hasDeposits,
  advanced,
  advancedCount = 0,
}: {
  values: SpaceOptionValues;
  onChange: (values: SpaceOptionValues) => void;
  disabled?: boolean;
  hasDeposits?: boolean;
  advanced?: ReactNode;
  advancedCount?: number;
}) {
  const { t } = useTranslation();
  const retentionOptions = useRetentionOptions();
  const set = (patch: Partial<SpaceOptionValues>) =>
    onChange({ ...values, ...patch });
  // Checked iff a date is set: checking picks one, clearing it unchecks,
  // so the box never claims an expiry the space won't get.
  const hasExpiry = values.expires_at !== null;
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // The earliest end date is today: the link then closes tonight.
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  // A closed fold still says what it holds, as on the transfer form.
  const activeCount =
    Number(values.single_use) + Number(!values.verify_email) + advancedCount;

  return (
    <div className="deposits__options">
      <Select
        label={t("Deposit validity duration")}
        variant="classic"
        fullWidth
        options={retentionOptions}
        value={String(values.retention_days)}
        clearable={false}
        disabled={disabled}
        onChange={(e) => set({ retention_days: Number(e.target.value) })}
      />
      <div className="deposits__field-group">
        <Checkbox
          label={t("Deposit space expiration date")}
          checked={hasExpiry}
          disabled={disabled}
          onChange={(e) => {
            const inAMonth = new Date();
            inAMonth.setDate(inAMonth.getDate() + 30);
            set({
              expires_at: e.currentTarget.checked
                ? endOfDayIso(dateInputValue(inAMonth.toISOString()))
                : null,
            });
          }}
        />
        {hasExpiry && (
          <DatePicker
            label={t("Deposit space expiration date")}
            hideLabel
            variant="classic"
            fullWidth
            minValue={today.toISOString()}
            value={values.expires_at}
            disabled={disabled}
            // The picker gives the day's start; the link closes at its end.
            onChange={(value) =>
              set({
                expires_at: value ? endOfDayIso(dateInputValue(value)) : null,
              })
            }
          />
        )}
      </div>

      <div className="deposits__advanced">
        <button
          type="button"
          className="deposits__advanced-toggle"
          aria-expanded={advancedOpen}
          aria-controls="space-options-advanced"
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          <Icon
            name={advancedOpen ? "keyboard_arrow_down" : "keyboard_arrow_right"}
          />
          <span>{t("Advanced options")}</span>
          {!advancedOpen && activeCount > 0 && (
            <span className="deposits__advanced-active">
              {t("{{count}} selected", { count: activeCount })}
            </span>
          )}
        </button>
        {advancedOpen && (
          <div id="space-options-advanced" className="deposits__advanced-list">
            <Checkbox
              label={
                hasDeposits
                  ? t("Close the link after the next deposit")
                  : t("Close the link after the first deposit")
              }
              checked={values.single_use}
              disabled={disabled}
              onChange={(e) => set({ single_use: e.currentTarget.checked })}
            />
            <Checkbox
              label={t("Disable email address verification")}
              text={t(
                "Removes the step that confirms the depositor's identity: their deposits are marked “address not verified”.",
              )}
              checked={!values.verify_email}
              disabled={disabled}
              onChange={(e) => set({ verify_email: !e.currentTarget.checked })}
            />
            {advanced}
          </div>
        )}
      </div>
    </div>
  );
}
