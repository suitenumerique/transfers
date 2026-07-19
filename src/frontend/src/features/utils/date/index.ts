import {
  differenceInCalendarDays,
  format,
  formatDistanceToNowStrict,
  isPast,
  isToday,
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

// Under a minute we say "just now" rather than a precise "46 seconds ago",
// which carries no useful information — same convention as most tools.
const JUST_NOW_MS = 60_000;

// Smart, human-friendly label:
//   - within a minute → "just now" ("À l'instant")
//   - same day → exact distance in hours/minutes ("il y a 3 heures")
//   - yesterday / tomorrow → the word + the time ("hier à 14:30")
//   - ≥ 2 calendar days away → a calendar-day count ("il y a 2 jours",
//     "dans 8 jours")
// The day bucket is counted in *calendar days*, not elapsed time: the
// "yesterday" label owns the −1 day slot, so this bucket starts at 2 days and
// never produces a "1 day ago" that would clash with it. The precise date +
// time always stays available on hover.
export function formatSmartDate(
  iso: string,
  lang: string,
  t: TFunction,
): string {
  const date = new Date(iso);
  const now = new Date();
  const locale = localeFor(lang);

  // All labels stay lowercase so they read correctly both standalone (the
  // activity log) and embedded mid-sentence ("Expire demain à 11:12") — and
  // they stay consistent with date-fns' lowercase "il y a 3 heures".
  if (Math.abs(now.getTime() - date.getTime()) < JUST_NOW_MS) {
    return t("just now");
  }
  if (isToday(date)) {
    return formatDistanceToNowStrict(date, { addSuffix: true, locale });
  }
  if (isYesterday(date)) {
    return t("yesterday at {{time}}", { time: format(date, "p", { locale }) });
  }
  if (isTomorrow(date)) {
    return t("tomorrow at {{time}}", { time: format(date, "p", { locale }) });
  }
  const days = differenceInCalendarDays(date, now); // <0 past, >0 future
  return days < 0
    ? t("{{count}} days ago", { count: -days })
    : t("in {{count}} days", { count: days });
}

// True if the timestamp is in the past. Kept here (not inline in a component)
// so the "now" comparison doesn't trip the React Compiler purity rule against
// calling impure clock functions during render.
export function isExpired(iso: string): boolean {
  return isPast(new Date(iso));
}
