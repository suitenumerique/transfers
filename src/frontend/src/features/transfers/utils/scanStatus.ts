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
