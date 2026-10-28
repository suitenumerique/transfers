import type { DepositSpace } from "@/features/api/types";

// Whether a space's link still takes deposits. The backend decides; this
// mirrors it for display.
export function spaceIsOpen(space: DepositSpace): boolean {
  if (space.used_at) return false;
  return !space.expires_at || new Date(space.expires_at) > new Date();
}

// The key of an end-to-end space never reaches the server: the browser that
// created the space keeps it, so the agent can copy the full link again.
const keyStorageName = (spaceId: string) => `deposit-space-key:${spaceId}`;
// Also kept for this page's life, should storage be blocked.
const sessionKeys = new Map<string, string>();

export function rememberSpaceKey(spaceId: string, fragment: string) {
  sessionKeys.set(spaceId, fragment);
  try {
    localStorage.setItem(keyStorageName(spaceId), fragment);
  } catch {
    // Storage blocked: the agent only gets the link once, on creation.
  }
}

export function recallSpaceKey(spaceId: string): string | null {
  const known = sessionKeys.get(spaceId);
  if (known) return known;
  try {
    return localStorage.getItem(keyStorageName(spaceId));
  } catch {
    return null;
  }
}

export function depositLink(space: DepositSpace, key?: string | null): string {
  const base = `${window.location.origin}/d/${space.link_token}`;
  return key ? `${base}#${key}` : base;
}

// A day as YYYY-MM-DD, local time ↔ the end of that day.
export function dateInputValue(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function endOfDayIso(value: string): string | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d, 23, 59, 59).toISOString();
}
