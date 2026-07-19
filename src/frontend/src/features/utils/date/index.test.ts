import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { format } from "date-fns";
import { enUS, fr } from "date-fns/locale";
import type { TFunction } from "i18next";
import {
  formatFullDateTime,
  formatSmartDate,
  isExpired,
  localeFor,
} from "./index";

// Minimal t(): no translation, just interpolation — lets us assert the
// composition logic ("<word> at <time>") without loading i18n resources.
const t = ((key: string, opts?: Record<string, unknown>) =>
  opts
    ? key.replace(/\{\{(\w+)\}\}/g, (_m, k: string) => String(opts[k]))
    : key) as unknown as TFunction;

// Fixed "now": 17 June 2026, 12:00 local. Midday keeps the ±26h offsets
// safely inside the neighbouring calendar days regardless of timezone.
const NOW = new Date(2026, 5, 17, 12, 0, 0);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("localeFor", () => {
  it("maps fr* to the French locale, everything else to en-US", () => {
    expect(localeFor("fr-FR")).toBe(fr);
    expect(localeFor("fr")).toBe(fr);
    expect(localeFor("en-US")).toBe(enUS);
    expect(localeFor("de-DE")).toBe(enUS);
  });
});

describe("formatSmartDate", () => {
  it("today → exact relative distance, both directions and locales", () => {
    const threeHoursAgo = new Date(2026, 5, 17, 9, 0, 0).toISOString();
    const inThreeHours = new Date(2026, 5, 17, 15, 0, 0).toISOString();
    // Exact wording, no fuzzy "environ"/"about" (we use the strict variant).
    expect(formatSmartDate(threeHoursAgo, "fr-FR", t)).toBe("il y a 3 heures");
    expect(formatSmartDate(threeHoursAgo, "en-US", t)).toBe("3 hours ago");
    expect(formatSmartDate(inThreeHours, "fr-FR", t)).toBe("dans 3 heures");
    expect(formatSmartDate(inThreeHours, "en-US", t)).toBe("in 3 hours");
  });

  it("within a minute → 'just now' (no useless seconds)", () => {
    const thirtySecAgo = new Date(2026, 5, 17, 11, 59, 30).toISOString();
    const fortySecAhead = new Date(2026, 5, 17, 12, 0, 40).toISOString();
    expect(formatSmartDate(thirtySecAgo, "fr-FR", t)).toBe("just now");
    expect(formatSmartDate(fortySecAhead, "en-US", t)).toBe("just now");
    // Just over a minute → a real distance, not "just now".
    const seventySecAgo = new Date(2026, 5, 17, 11, 58, 50).toISOString();
    expect(formatSmartDate(seventySecAgo, "en-US", t)).not.toBe("just now");
  });

  it("yesterday → lowercase 'yesterday at <time>' with localized time", () => {
    const d = new Date(2026, 5, 16, 9, 30, 0);
    expect(formatSmartDate(d.toISOString(), "en-US", t)).toBe(
      `yesterday at ${format(d, "p", { locale: enUS })}`,
    );
    expect(formatSmartDate(d.toISOString(), "fr-FR", t)).toBe(
      `yesterday at ${format(d, "p", { locale: fr })}`,
    );
  });

  it("tomorrow → lowercase 'tomorrow at <time>'", () => {
    const d = new Date(2026, 5, 18, 16, 0, 0);
    expect(formatSmartDate(d.toISOString(), "en-US", t)).toBe(
      `tomorrow at ${format(d, "p", { locale: enUS })}`,
    );
  });

  it("≥ 2 calendar days in the past → calendar-day count", () => {
    // fake t() only interpolates, so we assert the (en) key shape + count.
    const fiveDaysAgo = new Date(2026, 5, 12, 8, 0, 0).toISOString();
    expect(formatSmartDate(fiveDaysAgo, "en-US", t)).toBe("5 days ago");
  });

  it("≥ 2 calendar days in the future → calendar-day countdown", () => {
    const tenDaysAhead = new Date(2026, 5, 27, 8, 0, 0).toISOString();
    expect(formatSmartDate(tenDaysAhead, "en-US", t)).toBe("in 10 days");
  });

  it("47 h ago → '2 days ago', not '1 day ago' (that's yesterday's slot)", () => {
    // 15 June 13:00 vs NOW 17 June 12:00 = 47 h elapsed but 2 calendar days.
    const fortySevenHoursAgo = new Date(2026, 5, 15, 13, 0, 0).toISOString();
    expect(formatSmartDate(fortySevenHoursAgo, "en-US", t)).toBe("2 days ago");
    expect(formatSmartDate(fortySevenHoursAgo, "en-US", t)).not.toBe(
      "1 day ago",
    );
  });
});

describe("isExpired", () => {
  it("is true for past timestamps, false for future ones", () => {
    expect(isExpired(new Date(2026, 5, 17, 11, 0, 0).toISOString())).toBe(true);
    expect(isExpired(new Date(2026, 5, 17, 13, 0, 0).toISOString())).toBe(
      false,
    );
  });
});

describe("formatFullDateTime", () => {
  it("returns a full localized date + time string", () => {
    const d = new Date(2026, 5, 17, 14, 30, 0);
    expect(formatFullDateTime(d.toISOString(), "fr-FR")).toBe(
      format(d, "PPPp", { locale: fr }),
    );
  });
});
