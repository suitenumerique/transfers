// Default page size for the API
export const DEFAULT_PAGE_SIZE = 20;

// Session storage keys
export const APP_STORAGE_PREFIX = "transferts_";
export const SESSION_EXPIRED_KEY = APP_STORAGE_PREFIX + "session_expired";

// Theme
export const THEME_KEY = APP_STORAGE_PREFIX + "theme";

// LaGaufre — Suite territoriale (ANCT) widget endpoints.
// Borrowed from suitenumerique/drive's anct-light theme. The apiUrl is scoped
// to a specific operator/siret; we'll get our own identifiers later.
export const TERRITORIALE_GAUFRE = {
  widgetPath: "https://static.suite.anct.gouv.fr/widgets/lagaufre.js",
  apiUrl:
    "https://operateurs.suite.anct.gouv.fr/api/v1.0/lagaufre/services/?operator=9f5624fc-ef99-4d10-ae3f-403a81eb16ef&siret=21870030000013",
};
