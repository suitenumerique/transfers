// @vitest-environment node
//
// Unit tests for the scan-blocking predicate. Extracted from TransferForm's
// submitError auto-clear effect so the retry / timeout interaction has a
// place to regress. The prior implementation only inspected file statuses,
// so a ``scan_timeout`` submit error raised while files were still
// ``pending`` would be cleared instantly by the same effect that was
// supposed to preserve it.

import { describe, expect, it } from "vitest";
import type { ScanStatus } from "@/features/api/types";
import { isScanBlocking } from "./scanStatus";

const file = (scanStatus: ScanStatus | undefined) => ({ scanStatus });

const statusOf = (f: { scanStatus: ScanStatus | undefined }) => f.scanStatus;

describe("isScanBlocking", () => {
  it("blocks while scanTimedOut is set even if every file is still pending", () => {
    // Regression: this is the ``scan_timeout`` case. Submit raises the
    // banner, files remain ``pending`` (the poller just gave up, the
    // verdicts haven't landed). A files-only predicate would return
    // false and clear the banner on the very next render.
    expect(isScanBlocking([file("pending")], statusOf, true)).toBe(true);
  });

  it("unblocks once retryScan clears the timeout, even with pending files", () => {
    // ``retryScan`` sets ``scanTimedOut`` back to false and re-arms the
    // poller with a fresh deadline; the banner should clear then even if
    // no per-file status has moved yet.
    expect(isScanBlocking([file("pending")], statusOf, false)).toBe(false);
  });

  it("stays blocking while a file is in error, regardless of timeout", () => {
    // Transient scanner failure the retry loop is expected to unstick;
    // the "Retry the scan" advice remains accurate until the retry
    // lands and the row flips clean.
    expect(isScanBlocking([file("error"), file("clean")], statusOf, false)).toBe(
      true,
    );
  });

  it("stays blocking while a file is infected, regardless of timeout", () => {
    // Virus verdict — user has to remove the file. Banner stays until
    // then, even if other files are fine.
    expect(
      isScanBlocking([file("infected"), file("clean")], statusOf, false),
    ).toBe(true);
  });

  it("unblocks when nothing is timed out and every file has a non-blocking verdict", () => {
    // All clean / skipped / too_large — the underlying scan condition
    // has resolved, banner is stale advice, clear it.
    expect(
      isScanBlocking(
        [file("clean"), file("skipped"), file("too_large")],
        statusOf,
        false,
      ),
    ).toBe(false);
  });

  it("unblocks on an empty file list with no timeout", () => {
    expect(isScanBlocking([], statusOf, false)).toBe(false);
  });

  it("blocks on an empty file list if the timeout is active", () => {
    // Edge case — user removed the last file after the scan timed out.
    // scanTimedOut alone is enough to keep the banner up; the useEffect
    // above the predicate also depends on file-count so this branch
    // would rearm anyway, but the predicate itself must still say true.
    expect(isScanBlocking([], statusOf, true)).toBe(true);
  });
});
