import { apiFetch } from "@/features/api/client";

// The claim link's token waits here across the sign-in round trip: the
// login returns to the home page, which resumes the claim.
const PENDING_CLAIM_KEY = "transfers.pendingInboundClaim";

export function claimInbound(token: string) {
  return apiFetch<{ id: string }>("/inbox/claim/", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export function rememberPendingClaim(token: string) {
  try {
    sessionStorage.setItem(PENDING_CLAIM_KEY, token);
  } catch {
    // Storage blocked: the agent reopens the link after signing in.
  }
}

export function takePendingClaim(): string | null {
  try {
    const token = sessionStorage.getItem(PENDING_CLAIM_KEY);
    sessionStorage.removeItem(PENDING_CLAIM_KEY);
    return token;
  } catch {
    return null;
  }
}
