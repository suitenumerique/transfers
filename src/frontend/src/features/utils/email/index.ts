// TLD must be ≥2 chars to match Django's EmailValidator on the backend —
// otherwise `sd@asdl.c` passes here and gets rejected by the API.
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export const isValidEmail = (value: string) => EMAIL_RE.test(value.trim());

// Mirrors the backend's inbox_email_allowed: whole address, any case. A
// pattern JS can't read lets the address through: the API still decides.
export function inboxRecipientAllowed(pattern: string, email: string) {
  if (!pattern) return true;
  try {
    return new RegExp(`^(?:${pattern})$`, "i").test(email.trim());
  } catch {
    return true;
  }
}
