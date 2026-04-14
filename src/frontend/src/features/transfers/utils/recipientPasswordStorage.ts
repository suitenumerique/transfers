// Recipient-side password persistence.
//
// When a recipient successfully unlocks a protected transfer, their password
// is kept in localStorage keyed by the public token. On subsequent visits
// from the same browser the download page auto-loads it so they don't have
// to re-type the password. Stored locally only — the password never leaves
// the recipient's device and is not sent anywhere beyond the Authorization
// header on the download endpoints.

const KEY_PREFIX = "transferts.recipient.password.";

function key(publicToken: string): string {
  return `${KEY_PREFIX}${publicToken}`;
}

function safeStorage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

export function saveRecipientPassword(
  publicToken: string,
  password: string,
): void {
  const s = safeStorage();
  if (!s) return;
  try {
    s.setItem(key(publicToken), password);
  } catch {
    // Quota full / disabled — just skip.
  }
}

export function getRecipientPassword(publicToken: string): string | null {
  const s = safeStorage();
  if (!s) return null;
  try {
    return s.getItem(key(publicToken));
  } catch {
    return null;
  }
}

export function clearRecipientPassword(publicToken: string): void {
  const s = safeStorage();
  if (!s) return;
  try {
    s.removeItem(key(publicToken));
  } catch {
    // ignore
  }
}
