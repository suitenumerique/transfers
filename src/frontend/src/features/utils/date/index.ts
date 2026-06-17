import {
  format,
  formatDistanceToNow,
  isPast,
  isTomorrow,
  isYesterday,
} from "date-fns";
import { enUS, fr } from "date-fns/locale";
import type { Locale } from "date-fns";
import type { TFunction } from "i18next";

// Map the i18next language tag ("fr-FR", "en-US"…) to a date-fns locale.
// Anything that isn't French falls back to US English, matching the app's
// two supported languages. Extend here when a new locale is added.
export function localeFor(lang: string): Locale {
  return lang.toLowerCase().startsWith("fr") ? fr : enUS;
}

// Full, unambiguous date + time — used for the hover tooltip in every case.
// e.g. fr: "25 décembre 2026 à 14:30" — en: "December 25th, 2026 at 2:30 PM".
export function formatFullDateTime(iso: string, lang: string): string {
  return format(new Date(iso), "PPPp", { locale: localeFor(lang) });
}

// Smart, human-friendly label:
//   - yesterday / tomorrow → the word + the time ("hier à 14:30")
//   - everything else → relative distance, past or future ("il y a 2 h",
//     "il y a 8 jours", "dans 3 min", "dans 8 jours")
// We lean fully relative because date-fns never produces the awkward
// "avant-hier"/"day before yesterday" — it says "il y a 2 jours" / "2 days
// ago", which reads fine in both languages. The precise date + time always
// stays available on hover.
export function formatSmartDate(
  iso: string,
  lang: string,
  t: TFunction,
): string {
  const date = new Date(iso);
  const locale = localeFor(lang);

  if (isYesterday(date)) {
    return t("Yesterday at {{time}}", { time: format(date, "p", { locale }) });
  }
  if (isTomorrow(date)) {
    return t("Tomorrow at {{time}}", { time: format(date, "p", { locale }) });
  }
  return formatDistanceToNow(date, {
    addSuffix: true,
    includeSeconds: true,
    locale,
  });
}

// True if the timestamp is in the past. Kept here (not inline in a component)
// so the "now" comparison doesn't trip the React Compiler purity rule against
// calling impure clock functions during render.
export function isExpired(iso: string): boolean {
  return isPast(new Date(iso));
}
