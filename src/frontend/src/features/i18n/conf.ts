import { APP_STORAGE_PREFIX } from "../config/constants";
import { handle } from "../utils/errors";

const DEFAULT_LANGUAGES: [string, string][] = [["fr-FR","Français"],["en-US","English"]];

// TODO: Tackle async loading of languages from backend
// to avoid declaring languages in multiple places (backend and frontend)
function isLanguageList(value: unknown): value is [string, string][] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (item) =>
        Array.isArray(item) &&
        item.length === 2 &&
        typeof item[0] === "string" &&
        typeof item[1] === "string",
    )
  );
}

function getLanguagesFromEnv(): [string, string][] {
  const languages = import.meta.env.NEXT_PUBLIC_LANGUAGES;
  if (!languages) return DEFAULT_LANGUAGES;
  try {
    const parsed = JSON.parse(languages);
    if (!isLanguageList(parsed)) {
      handle(new Error("Invalid languages schema from env."), { extra: { languages } });
      return DEFAULT_LANGUAGES;
    }
    return parsed;
  } catch (error) {
    handle(new Error("Error parsing languages from env."), { extra: { error, languages } });
    return DEFAULT_LANGUAGES;
  }
}

export const LANGUAGES = getLanguagesFromEnv();
export const LANGUAGES_ALLOWED = LANGUAGES.map((language) => language[0]);
export const LANGUAGE_LOCAL_STORAGE = APP_STORAGE_PREFIX + 'language';
const DEFAULT_LANGUAGE_FROM_ENV = import.meta.env.NEXT_PUBLIC_DEFAULT_LANGUAGE;
export const BASE_LANGUAGE =
  DEFAULT_LANGUAGE_FROM_ENV && LANGUAGES_ALLOWED.includes(DEFAULT_LANGUAGE_FROM_ENV)
    ? DEFAULT_LANGUAGE_FROM_ENV
    : LANGUAGES_ALLOWED[0];
