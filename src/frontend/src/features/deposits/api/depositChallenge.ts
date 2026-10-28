import { apiFetch } from "@/features/api/client";

// The depositor's side, before the upload: ask for a one-time code, then
// trade it for the session token the deposit-draft calls carry.

export type DepositTarget =
  | { space_token: string }
  | { recipient_email: string };

export interface ChallengeStarted {
  challenge_id: string;
  expires_at: string;
}

export interface DepositSession {
  deposit_token: string;
  expires_at: string;
}

export function startDepositChallenge(
  target: DepositTarget,
  depositor: { depositor_name: string; depositor_email: string },
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
