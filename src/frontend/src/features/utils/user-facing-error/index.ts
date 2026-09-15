import i18n from "i18next";
import { ApiError } from "@/features/api/client";

// A ``fetch()`` that never reached a server rejects with a TypeError whose
// message is browser-specific ("Failed to fetch" on Chromium, "NetworkError
// when attempting to fetch resource." on Firefox, "Load failed" on Safari).
// No status, no body: the only reliable signal is the type.
export function isNetworkError(err: unknown): boolean {
  if (err instanceof ApiError) return false;
  if (err instanceof TypeError) return true;
  return (
    err instanceof Error &&
    err.name === "UploadPartError" &&
    /network error/i.test(err.message)
  );
}

// What to show a user for an error that surfaced from an upload or an API
// call. Server-supplied 4xx details are meaningful and pass through; the
// rest is a fixed sentence instead of an exception's ``toString()``.
export function userFacingError(err: unknown): string {
  if (isNetworkError(err)) {
    return i18n.t("Can't reach the server. Check your connection and try again.");
  }
  if (err instanceof ApiError) {
    if (err.status >= 500) {
      return i18n.t("The server ran into an error. Try again in a moment.");
    }
    if (err.message && err.message !== err.body) return err.message;
  }
  if (err instanceof Error && err.name === "UploadPartError") {
    return i18n.t("The upload failed. Remove the file and add it again.");
  }
  return i18n.t("Something went wrong. Try again.");
}
