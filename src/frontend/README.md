# Transfers frontend

[Vite](https://vite.dev/) single-page app with file-based routing via
[TanStack Router](https://tanstack.com/router/), built to static assets and
served through Caddy. Uses
[Cunningham](https://github.com/numerique-gouv/cunningham) for the
component kit, [TanStack Query](https://tanstack.com/query) for server
state, and [i18next](https://www.i18next.com/) for translations.

## Getting started

```bash
npm install
npm run dev      # Vite dev server on http://localhost:3000 (8980 via `make`)
npm run build    # type-check + production build into dist/
npm run preview  # serve the production build locally
```

## Layout

```text
src/
├── routes/                 # TanStack Router file-based routes
│   ├── __root.tsx          # Providers (Query, Cunningham, Config, Auth)
│   ├── _app.tsx            # Pathless layout wrapping the app shell
│   ├── _app/index.tsx      # Home — new transfer form
│   ├── _app/transfers/$id.tsx  # Transfer detail (owner view)
│   ├── _app/confirm/$id.tsx        # Post-finalize confirmation
│   ├── _app/confirm-failed/$id.tsx # Email-mode partial-failure landing
│   └── t/$token.tsx        # Public download page (recipient view)
├── features/
│   ├── api/                # Shared API client (apiFetch, ApiError, types)
│   ├── transfers/
│   │   ├── api/            # TanStack Query hooks against the backend
│   │   ├── components/     # TransferForm, TransferDetail, FileDropZone, …
│   │   └── upload/         # Multipart-upload state machine (browser-side)
│   ├── auth/               # ProConnect session bridge
│   ├── config/             # Frontend runtime config from /api/config/
│   ├── i18n/               # i18next setup
│   ├── layouts/            # Shell, Sidebar, TopBar
│   ├── providers/          # React Query client, Cunningham theme, …
│   ├── ui/                 # Shared components (modals, toasts, …)
│   └── utils/              # Misc helpers (debounced value, error mapping, …)
├── styles/                 # Global SCSS + Cunningham generated tokens
└── caddy/Caddyfile         # Reverse proxy config (XFF propagation, SPA fallbacks)
```

## Translations

Strings are extracted with `i18next-cli` (`npm run i18n:extract`) into
`public/locales/<namespace>/<lang>.json` — currently a single `common`
namespace with English (`en-US`) and French (`fr-FR`).

## Caddy

The static export is served by Caddy in production, which also reverse-
proxies `/api/*`, `/admin/*`, `/static/*`, and `/__heartbeat__/*` to
the Django backend.

Caddy establishes the client address itself rather than passing the edge
router's header through: `trusted_proxies_strict` walks `X-Forwarded-For`
right to left and stops at the first address that is not a trusted proxy.
The backend is then sent that single resolved address as `X-Forwarded-For`
(`{client_ip}`). Set `TRANSFERS_FRONTEND_TRUSTED_PROXIES` to the edge's
CIDRs, or the address Caddy resolves is the edge itself. See the comments
in `caddy/Caddyfile`.

A prefix a client appended therefore loses — but only for as long as that
list holds nothing but real proxies. The walk skips every entry it finds
trusted, so a CIDR wide enough to cover a client's own address lets it
carry on leftwards into the part of the header that client wrote. Keep it
to the edge, never a broad range.

`XForwardedForMiddleware` is what reads that rightmost entry into
`REMOTE_ADDR`, and it is installed only when `USE_X_FORWARDED_FOR=True`,
which is **not** the default. Until it is on, `REMOTE_ADDR` stays the TCP
peer — Caddy — so the audit log records Caddy's address for every request
and DRF's anonymous throttles (`NUM_PROXIES = 0`) hold every client in a
single bucket. Turn it on once nothing but Caddy can reach the backend:
on a backend reachable directly, the header is whatever the caller chose
to send.

Any other topology owes the backend the same guarantee: the hop in front
of Django must **append** the address it observed, or replace the header
outright. One that passes a client-written `X-Forwarded-For` through
unchanged leaves the rightmost entry under the client's control, and that
address is what DRF's anonymous throttles key on and what the audit log
records. The admin IP allowlist is unaffected either way -- Caddy answers
403 on its own `client_ip` before proxying, and Django never checks it --
so a deployment that exposes the backend without Caddy in front loses the
allowlist entirely, whatever this header says.

## Further reading

- [`../../README.md`](../../README.md) — project setup, La Suite
  Drive integration, environment variables.
- [`../../docs/S3.md`](../../docs/S3.md) — backend storage model
  (relevant if you change anything in `features/transfers/upload/`).
