# Transferts frontend

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
the Django backend. The `Caddyfile` propagates `X-Forwarded-For` from
Scalingo's edge router as-is (do **not** use `{remote_host}` — see the
comment in `caddy/Caddyfile`).

## Further reading

- [`../../README.md`](../../README.md) — project setup, La Suite
  Drive integration, environment variables.
- [`../../docs/S3.md`](../../docs/S3.md) — backend storage model
  (relevant if you change anything in `features/transfers/upload/`).
