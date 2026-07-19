# Authentication

In production, Transfers authenticates agents through **ProConnect** (AgentConnect)
over OIDC. For local development there is no ProConnect instance, so the dev stack
ships a **local Keycloak** that plays the same role: the app runs the *real* OIDC
code flow, just against a self-hosted provider.

## Signing in locally

1. `docker compose up -d` (or `make bootstrap`) — this starts the `keycloak` service.
2. Open http://localhost:8980 and click **Sign in**.
3. Log in with one of the seeded test users:

   | Username / email           | Password     |
   |----------------------------|--------------|
   | `agent@collectivite.fr`    | `transferts` |
   | `agent2@collectivite.fr`   | `transferts` |

That's it — you land back in the app, authenticated. Logout works the same way
(it clears both the Django session and the Keycloak SSO session).

**Keycloak admin console:** http://localhost:8902 — realm `master`, `admin` / `admin`.
This admin manages *Keycloak itself*; it is unrelated to the app's test users
(which live in the `transferts` realm). Both the admin credentials and the realm
are dev-only — see [Security note](#security-note).

## How it's wired

```text
 Browser ──Sign in──▶ /api/v1.0/authenticate/ (backend)
        ◀──302── redirect to Keycloak authorize  (http://localhost:8902/...)
 Browser ──login form──▶ Keycloak
        ◀──302── redirect to /api/v1.0/callback/?code=...  (backend)
 Backend ──exchange code──▶ Keycloak token/userinfo  (http://keycloak:8802/...)
        ── creates/updates the User, sets the session cookie ──▶ app
```

### The two-hostname split

The browser and the backend reach Keycloak on **different hostnames**:

- the **browser** is redirected to the authorize / logout endpoints on
  `http://localhost:8902` (the published host port);
- the **backend** calls the token / userinfo / JWKS endpoints on
  `http://keycloak:8802` (the in-network service name — `localhost:8902` is
  unreachable from inside the backend container).

To keep the two consistent, Keycloak is started with
`--hostname=http://localhost:8902`, so every URL and the `iss` claim it issues
are stamped with `localhost:8902` regardless of which host answered the request.
This split is configured in `env.d/development/backend.defaults`:

```bash
# browser-facing
OIDC_OP_AUTHORIZATION_ENDPOINT=http://localhost:8902/realms/transferts/protocol/openid-connect/auth
OIDC_OP_LOGOUT_ENDPOINT=http://localhost:8902/realms/transferts/protocol/openid-connect/logout
# backend-facing (in-network)
OIDC_OP_TOKEN_ENDPOINT=http://keycloak:8802/realms/transferts/protocol/openid-connect/token
OIDC_OP_USER_ENDPOINT=http://keycloak:8802/realms/transferts/protocol/openid-connect/userinfo
OIDC_OP_JWKS_ENDPOINT=http://keycloak:8802/realms/transferts/protocol/openid-connect/certs
```

> This is the same pattern as the S3 dev setup (`AWS_S3_DOMAIN_REPLACE`):
> internal service name for backend calls, `localhost` for the browser.

### The realm

The `transferts` realm — client `transferts` (confidential, secret
`transferts-dev-secret`) and the test users — is imported on startup from
[`src/keycloak/realm.json`](../src/keycloak/realm.json) via `--import-realm`.
The client allows redirects to `localhost:8980` (frontend) and `localhost:8981`
(the backend OIDC callback). Keycloak runs with `start-dev`, so its database is
an **ephemeral H2** that resets whenever the container is recreated — the realm
(and the admin) are re-imported each fresh start.

### Adding or editing users

Either edit `src/keycloak/realm.json` and recreate Keycloak
(`docker compose up -d --force-recreate keycloak`), or add them at runtime in the
admin console (realm `transferts`). Runtime changes are lost on the next recreate
since the H2 store is ephemeral — put anything you want to keep in `realm.json`.

## Switching to the real ProConnect

The dev OIDC config lives in the committed `env.d/development/backend.defaults`
and points at the local Keycloak. To target the real AgentConnect integration env
instead, uncomment the ProConnect block in your (git-ignored)
`env.d/development/backend.local` — it overrides the defaults and restores the
`fca.integ01.dev-agentconnect.fr` endpoints plus the real client id/secret.

## Security note

Everything here is **dev-only**: weak admin credentials, a committed dev client
secret, `sslRequired: none`, `start-dev`, and an ephemeral database. None of it
applies to production, where a real ProConnect/Keycloak deployment is configured
through environment variables (real endpoints, real secrets, persistent storage).

## Troubleshooting

- **"Invalid redirect uri"** on login/logout → the URL isn't in the client's
  `redirectUris` / `post.logout.redirect.uris` in `realm.json`. Both
  `localhost:8980/*` and `localhost:8981/*` must be allowed.
- **"Invalid parameter: id_token_hint"** on logout → you recreated Keycloak while
  a session held an id_token signed by the *previous* Keycloak key. Log in again;
  the fresh token logs out cleanly.
- **Empty `full_name`** → `OIDC_USERINFO_FULLNAME_FIELDS` must be a bare
  comma-separated list (`given_name,family_name`), not JSON — django-configurations
  `ListValue` splits on commas.
