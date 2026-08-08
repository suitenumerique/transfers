import type { ScanStatus } from "@/features/api/types";

// Statuses that mean "this file finalized without an antivirus verdict"
// (either the scanner never got a chance, or the file itself couldn't be
// scanned). Shared with the header alerts that warn the user before Send,
// on the recap screen, and to the recipient — all three surfaces treat the
// same three states as "not scan-verified".
const NOT_SCAN_VERIFIED: readonly ScanStatus[] = [
  "skipped",
  "too_large",
  "error",
];

// Returns true when at least one file finished with a scan status that
// isn't a clean verdict. ``statusOf`` picks the field name — camelCase
// (``scanStatus``) on the pre-Send ``DraftFile``, snake_case
// (``scan_status``) on server-side transfer records — so the same
// predicate serves both sides without duplicating the state list.
export function hasUnscannedFiles<T>(
  files: readonly T[],
  statusOf: (file: T) => ScanStatus | undefined,
): boolean {
  return files.some((f) =>
    NOT_SCAN_VERIFIED.includes((statusOf(f) ?? "") as ScanStatus),
  );
}

// Returns true when a scan-origin submit-error banner should still be
// considered "in progress" and therefore preserved. Three signals count
// as blocking:
//   - the client-side scan poller gave up (``scanTimedOut``): the
//     ``scan_timeout`` banner tells the user to Retry Scan; the file's
//     scan_status is still ``pending`` at that point, so a status-only
//     predicate would clear the banner immediately after the submit
//     that raised it. ``retryScan`` flips this back to ``false`` and
//     re-arms polling — that's when we want the banner to clear.
//   - any file with ``scan_status === "error"``: a transient scanner
//     failure the retry loop is expected to unstick; the banner's
//     "Retry the scan" advice remains accurate until the retry lands.
//   - any file with ``scan_status === "infected"``: a virus verdict
//     blocks the transfer until the file is removed; the banner tells
//     the user to remove it, still true as long as the file is there.
// Consumed by the ``submitError`` auto-clear effect in TransferForm.
export function isScanBlocking<T>(
  files: readonly T[],
  statusOf: (file: T) => ScanStatus | undefined,
  scanTimedOut: boolean,
): boolean {
  if (scanTimedOut) return true;
  return files.some((f) => {
    const s = statusOf(f);
    return s === "error" || s === "infected";
  });
}
