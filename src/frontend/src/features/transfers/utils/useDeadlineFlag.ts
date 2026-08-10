import { useEffect, useState } from "react";
import { isExpired } from "@/features/utils/date";

// setTimeout's delay is a 32-bit signed integer — a value beyond ~24.8 days
// wraps and fires immediately, so cap each schedule and re-arm on the next
// tick when the actual deadline is further out.
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
    // Recompute the remaining time on every tick so a deadline past the
    // single-timer ceiling (setTimeout's ~24.8-day cap) doesn't flip the
    // flag prematurely after MAX_TIMER_MS. Each firing re-arms the next
    // one until the actual deadline passes.
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const msUntil = new Date(deadlineIso).getTime() - Date.now();
      if (msUntil <= 0) {
        setFlag(true);
        return;
      }
      timer = setTimeout(tick, Math.min(msUntil, MAX_TIMER_MS));
    };
    tick();
    return () => clearTimeout(timer);
  }, [deadlineIso, enabled, flag]);
  return flag;
}
