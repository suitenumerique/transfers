import { apiFetch } from "@/features/api/client";

// The depositor's side, before the upload: ask for a one-time code, then
// trade it for the session token the deposit-draft calls carry.

export type DepositTarget =
  | { space_token: string }
  | { recipient_email: string };

// A code was mailed, or none was needed (a signed-in depositor, a space
// that does not check emails): the session then comes back at once.
export type ChallengeStarted =
  | { challenge_id: string; expires_at: string; deposit_token?: undefined }
  | { challenge_id: string; deposit_token: string; email_verified: boolean };

export interface DepositSession {
  deposit_token: string;
  expires_at: string;
}

// A signed-in depositor sends no name or email: their account's are used.
export function startDepositChallenge(
  target: DepositTarget,
  depositor: { depositor_name?: string; depositor_email?: string },
) {
  return apiFetch<ChallengeStarted>("/deposit-challenges/", {
    method: "POST",
    body: JSON.stringify({ ...target, ...depositor }),
  });
}

export function verifyDepositChallenge(challengeId: string, code: string) {
  return apiFetch<DepositSession>(
    `/deposit-challenges/${challengeId}/verify/`,
    {
      method: "POST",
      body: JSON.stringify({ code }),
    },
  );
}
