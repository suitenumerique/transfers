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
  const label = formatSmartDate(iso, i18n.language, t);
  const full = formatFullDateTime(iso, i18n.language);
  return (
    <Tooltip content={full} closeDelay={0}>
      <time dateTime={iso} className={className}>
        {label}
        {/* The hover tooltip is mouse-only and a <time> isn't focusable, so
            screen-reader / keyboard users would never reach the exact date.
            Expose it as visually-hidden (but a11y-tree-present) text. */}
        <span className="c__offscreen">{`, ${full}`}</span>
      </time>
    </Tooltip>
  );
}
