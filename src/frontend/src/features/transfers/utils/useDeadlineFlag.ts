import { useEffect, useState } from "react";
import { isExpired } from "@/features/utils/date";

// setTimeout wraps around 2^31 ms — for anything further out we set a
// shorter timer and re-arm on the next render. User-facing deadlines are
// typically well within this range so a single arm is enough in practice.
const MAX_TIMER_MS = 2_000_000_000;

// Returns a boolean that flips to true at ``deadlineIso`` (or immediately
// if already past) and re-arms automatically when the deadline changes.
// ``enabled`` gates the whole thing — pass e.g. ``isActive`` on the agent
// view so a deactivated transfer never re-arms its expiry timer. The
// recipient view enables it unconditionally.
//
// This is UX only; the security guarantee comes from the backend, which
// already 410s on any download attempt past ``expires_at``. What this
// buys is that the buttons disable at the exact deadline instead of
// letting the user click into an opaque error.
export function useDeadlineFlag(
  deadlineIso: string,
  enabled: boolean = true,
): boolean {
  const [flag, setFlag] = useState(() => enabled && isExpired(deadlineIso));
  useEffect(() => {
    if (flag || !enabled) return;
    const msUntil = new Date(deadlineIso).getTime() - Date.now();
    if (msUntil <= 0) {
      setFlag(true);
      return;
    }
    const timer = setTimeout(() => setFlag(true), Math.min(msUntil, MAX_TIMER_MS));
    return () => clearTimeout(timer);
  }, [deadlineIso, enabled, flag]);
  return flag;
}
