# End-to-end tests

Playwright drives Chromium through the whole app: real OIDC sign-in against
Keycloak, encrypted uploads to S3, emails sent by the worker, downloads
decrypted by the service worker.

## Running them

```bash
make e2e          # fresh stack, then every test
make e2e-test     # every test, on the stack already running
make e2e-test ARGS=tests/transfer-link.spec.ts   # any Playwright arguments
make e2e-report   # last HTML report, traces and videos: http://localhost:9323
make e2e-down     # stop the stack and drop its data
```

`make e2e-test` rebuilds the runner image only when `package.json` changes;
the tests are mounted, so an edit needs no rebuild.

### On the image we ship

The same specs also run against the production frontend image — distroless,
Caddy, the built bundle — instead of the dev server:

```bash
make e2e-prod       # fresh stack on the production image, then every test
make e2e-up-prod    # just the stack, to browse http://localhost:7980
make e2e-test-prod  # every test, on that stack (ARGS= as above)
make e2e-down       # same project name: tears down either stack
```

`compose.e2e.prod.yaml` overrides the `frontend` service only where the two
differ: the `runtime-prod` build target, `PORT=3000` so Caddy answers where
the dev server did (the specs and the port forwarder are untouched), the
health check the image cannot expand itself, and
`TRANSFERS_FRONTEND_S3_ORIGIN` so the CSP admits the local S3.
`TRANSFERS_FRONTEND_BACKEND_SERVER` needs no second value: Caddy and the dev
proxy read the same variable.

This run is the only one that exercises what production actually answers with:

- the **Content-Security-Policy** and the other security headers, enforced by
  the browser — including the `img-src` / `font-src` origins a theme's assets
  need;
- Caddy's **SPA fallback** on a cold deep link (`/t/<token>` typed straight
  in), with its `If-None-Match` stripping;
- the `Cache-Control` split between hashed assets and everything else;
- the `Host` Caddy forwards to Django, which is what the per-domain
  configuration resolves on in production;
- the minified, code-split bundle rather than modules transformed on demand.

It is also faster (~45 s against ~1.4 min) and holds at four workers, since
serving static files is no longer one Node process's job. What it costs: a
frontend source change needs an image rebuild, and a failure in minified code
reads less well. Write and debug specs on `make e2e`; `make e2e-prod` is the
one to trust before shipping.

## The stack

`compose.e2e.yaml` runs the whole app as the Compose project
`transfers-e2e`, beside the dev stack:

| Service | URL |
|---|---|
| Frontend | http://localhost:7980 |
| Frontend, as a second operator | http://opsn1.localhost:7980 |
| API | http://localhost:7981 |
| Keycloak | http://localhost:7902 (`admin` / `admin`) |
| Mail (maildev) | http://localhost:7984 |
| S3 | http://localhost:7986 |

- Postgres and S3 keep their data in memory: `make e2e-up` starts empty.
- The API is **same-origin**: the dev server proxies `/api` the way Caddy
  does in production, and the app derives its API origin from
  `window.location`. Pointing `NEXT_PUBLIC_API_ORIGIN` at port 7981 instead
  would test a topology we ship nowhere, and the per-domain configuration
  would resolve against that host rather than the one in the address bar.
- `opsn1.localhost:7980` is the **same container on a second name**, which is
  what gives the runtime configuration two domains to tell apart
  (`DEFAULT_CONFIG` / `CONFIG_OVERRIDES` in `env.d/e2e/backend.e2e`).
  Browsers resolve `*.localhost` to loopback on their own, so this needs no
  DNS and no `/etc/hosts`; Vite allows any `.localhost` host by default.
- The settings are the dev ones (`env.d/development/*.defaults`), overridden
  by `env.d/e2e/`: the URLs above, and rate limits raised so a full run from
  one IP is not throttled.
- The antivirus is off (`SCAN_ENABLED` defaults to false), so every file is
  "not scanned".
- The Keycloak realm is the dev one, `src/keycloak/realm.json`, which also
  allows the 79xx redirect URIs.

The runner (service `playwright`, profile `runner`) is the official Playwright
image with this folder's dependencies. The app hands out `localhost:79xx`
URLs (OIDC redirects, presigned S3 URLs, links in emails), so
`scripts/forward-ports.mjs` relays those ports to the services from inside
the runner, then starts the tests. The runner does not use the host network.

Reports, traces, videos and the saved sessions go to the `e2e-output` volume:
Playwright writes many files at once, which a network file system (sshfs)
handles badly. Set `E2E_OUTPUT_DIR` to a host folder to get them there (CI
does, to upload them on failure).

## Writing tests

- `tests/auth.setup.ts` signs `user1`, `user2` and `user3@example.local` in
  once (password: the name before the @) and saves their sessions. A test
  file starts from one with `test.use({ storageState: storageStateOf(USER1) })`.
- `anonymousPage(browser)` opens a page with no session. `browser.newPage()`
  would inherit the file's signed-in session.
- `waitForMail()` (`helpers/mail.ts`) reads maildev. Tests run in parallel
  and share mailboxes: find your email by a unique title in its body
  (`uniqueTitle()`), or by an address only your test uses.
- `makeFile()` writes random bytes; compare a download with
  `downloadedBytes(download)`.
- The suite runs **two workers**, not four. With a same-origin API the Vite
  dev server proxies every API call while also transforming modules for each
  freshly opened context, and one Node process doing both starves the API
  call a cold page load then makes: the download page sits on its spinner
  and the test times out. Production has no such shape (Caddy serves a built
  bundle), so this is the dev server's ceiling, not the app's.
- Select by role and visible text, as a user would. The app has no
  `data-testid`. When the sidebar repeats a name, scope the locator to the
  page's own list.

## What is covered

| File | Flows |
|---|---|
| `transfer-link.spec.ts` | Link transfer, anonymous download (bytes compared), history; single-use link closing after download |
| `transfer-confidential.spec.ts` | Key in the fragment; key prompt without it (malformed key refused); confidential email keeps the key out of the invitation |
| `transfer-email.spec.ts` | Invitations to two recipients, personal links, download receipt to the sender, recipient in the history; recipient input validation |
| `transfer-manage.spec.ts` | Sidebar search, deactivate, delete permanently; another agent cannot open the transfer |
| `public-pages.spec.ts` | Landing, language remembered, unknown links, sign-in error page, signed-out redirect, sign out |
| `theming.spec.ts` | One image, two operators: colours, font, logo, banner, favicon slots and ProConnect opt-in resolved per domain; the support link on the error page; `/config/` keyed on the browser's `Host`, an unknown theme key served untouched, an unknown section never served |

Not covered yet: the antivirus (infected, scan errors: needs the file-scanner
stack), Drive import, the validity choice, `Retry sending` (needs a failing
SMTP), the Django admin, the mobile layout.
