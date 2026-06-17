import { useTranslation } from "react-i18next";
import { Tooltip } from "@gouvfr-lasuite/cunningham-react";
import { formatFullDateTime, formatSmartDate } from "@/features/utils/date";

interface RelativeDateProps {
  /** ISO 8601 timestamp coming from the API. */
  iso: string;
  className?: string;
}

// Renders a human-friendly relative date ("il y a 2 h", "hier à 14:30", or an
// exact date) with the full date + time always available on hover. Locale
// follows the active i18n language. See ``features/utils/date`` for the rules.
export function RelativeDate({ iso, className }: RelativeDateProps) {
  const { t, i18n } = useTranslation();
  return (
    <Tooltip content={formatFullDateTime(iso, i18n.language)}>
      <time dateTime={iso} className={className}>
        {formatSmartDate(iso, i18n.language, t)}
      </time>
    </Tooltip>
  );
}
