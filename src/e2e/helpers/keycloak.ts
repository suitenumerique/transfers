import { randomUUID } from "node:crypto";
import type { DevUser } from "./auth";

// Keycloak's admin API (bootstrap admin of compose.e2e.yaml).
const KEYCLOAK_URL = "http://localhost:7902";

async function adminToken(): Promise<string> {
  const response = await fetch(
    `${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token`,
    {
      method: "POST",
      body: new URLSearchParams({
        grant_type: "password",
        client_id: "admin-cli",
        username: "admin",
        password: "admin",
      }),
    },
  );
  if (!response.ok) throw new Error(`Keycloak token: ${response.status}`);
  return ((await response.json()) as { access_token: string }).access_token;
}

// A new Keycloak user, unknown to the app until it signs in. For tests that
// change what an account owns (an email with an account gets its sends at
// once), so they don't depend on what earlier runs did.
export async function createUser(
  prefix = "e2e",
  domain = "example.local",
): Promise<DevUser> {
  const name = `${prefix}-${randomUUID().slice(0, 8)}`;
  const user = { email: `${name}@${domain}`, password: name };
  const response = await fetch(`${KEYCLOAK_URL}/admin/realms/transfers/users`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${await adminToken()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username: user.email,
      email: user.email,
      emailVerified: true,
      enabled: true,
      firstName: "E2E",
      lastName: name,
      credentials: [
        { type: "password", value: user.password, temporary: false },
      ],
    }),
  });
  if (response.status !== 201) {
    throw new Error(
      `Keycloak user creation: ${response.status} ${await response.text()}`,
    );
  }
  return user;
}
