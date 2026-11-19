import { useTranslation } from "react-i18next";
import { useConfig } from "@/features/providers/config";

// The retention choices a space may keep its deposits for.
export function useRetentionOptions() {
  const { t } = useTranslation();
  const config = useConfig();
  return config.DEPOSIT_SPACE_RETENTION_CHOICES.map((days) => ({
    // The field's label already says what is kept.
    label: t("{{count}} days", { count: days }),
    value: String(days),
  }));
}
