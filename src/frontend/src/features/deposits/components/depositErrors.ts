import i18n from "i18next";
import { ApiError } from "@/features/api/client";
import { userFacingError } from "@/features/utils/user-facing-error";

function reasonOf(err: unknown): string | undefined {
  if (!(err instanceof ApiError)) return undefined;
  return (err.body as { reason?: string } | undefined)?.reason;
}

// What to tell a depositor when a step fails. The backend's reasons first,
// then the generic upload / network messages.
export function depositErrorMessage(err: unknown): string {
  const reason = reasonOf(err);
  const t = i18n.t.bind(i18n);
  if (err instanceof ApiError && err.status === 429) {
    return t("Too many deposits or code requests for now. Try again later.");
  }
  switch (reason) {
    case "recipient_not_allowed":
      return t("Files can't be sent to this address here.");
    case "revoked":
      return t("This deposit link was closed by its owner.");
    case "not_found":
      return t("This deposit link does not exist.");
    case "disabled":
      return t("Sending files without an account is not available here.");
    case "expired":
      return t("This code has expired. Ask for a new one.");
    case "session":
      return t("Your deposit session has ended. Start again from the link.");
    case "closed":
      return t("This recipient no longer accepts deposits.");
    case "scan_blocked":
      return t("A virus was detected. Your deposit was blocked and not sent.");
    case "scan_file_error":
      return t(
        "A file could not be scanned and was blocked. Remove it to send the others.",
      );
    case "scan_error":
      return t("The antivirus scan could not complete. Try sending again.");
  }
  if (err instanceof Error && err.message === "finalize_timeout") {
    return t("Sending is taking too long. Please try again.");
  }
  return userFacingError(err);
}
