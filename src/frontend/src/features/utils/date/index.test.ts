import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { format, formatDistanceToNow } from "date-fns";
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
  it("today → relative distance, both directions and locales", () => {
    const twoHoursAgo = new Date(2026, 5, 17, 10, 0, 0).toISOString();
    const inTwoHours = new Date(2026, 5, 17, 14, 0, 0).toISOString();
    expect(formatSmartDate(twoHoursAgo, "en-US", t)).toMatch(/ago$/);
    expect(formatSmartDate(twoHoursAgo, "fr-FR", t)).toMatch(/^il y a/);
    expect(formatSmartDate(inTwoHours, "en-US", t)).toMatch(/^in /);
    expect(formatSmartDate(inTwoHours, "fr-FR", t)).toMatch(/^dans /);
  });

  it("yesterday → 'Yesterday at <time>' with localized time", () => {
    const d = new Date(2026, 5, 16, 9, 30, 0);
    expect(formatSmartDate(d.toISOString(), "en-US", t)).toBe(
      `Yesterday at ${format(d, "p", { locale: enUS })}`,
    );
    expect(formatSmartDate(d.toISOString(), "fr-FR", t)).toBe(
      `Yesterday at ${format(d, "p", { locale: fr })}`,
    );
  });

  it("tomorrow → 'Tomorrow at <time>'", () => {
    const d = new Date(2026, 5, 18, 16, 0, 0);
    expect(formatSmartDate(d.toISOString(), "en-US", t)).toBe(
      `Tomorrow at ${format(d, "p", { locale: enUS })}`,
    );
  });

  it("≥ 2 days in the past → relative distance ('il y a X jours', never 'avant-hier')", () => {
    const fiveDaysAgo = new Date(2026, 5, 12, 8, 0, 0);
    expect(formatSmartDate(fiveDaysAgo.toISOString(), "fr-FR", t)).toBe(
      formatDistanceToNow(fiveDaysAgo, {
        addSuffix: true,
        includeSeconds: true,
        locale: fr,
      }),
    );
    expect(formatSmartDate(fiveDaysAgo.toISOString(), "fr-FR", t)).toMatch(
      /^il y a /,
    );
  });

  it("≥ 2 days in the future → relative distance (countdown)", () => {
    const tenDaysAhead = new Date(2026, 5, 27, 8, 0, 0);
    expect(formatSmartDate(tenDaysAhead.toISOString(), "fr-FR", t)).toBe(
      formatDistanceToNow(tenDaysAhead, {
        addSuffix: true,
        includeSeconds: true,
        locale: fr,
      }),
    );
    expect(formatSmartDate(tenDaysAhead.toISOString(), "fr-FR", t)).toMatch(
      /^dans /,
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
