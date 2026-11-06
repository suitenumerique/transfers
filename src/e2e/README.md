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

## The stack

`compose.e2e.yaml` runs the whole app as the Compose project
`transfers-e2e`, beside the dev stack:

| Service | URL |
|---|---|
| Frontend | http://localhost:7980 |
| API | http://localhost:7981 |
| Keycloak | http://localhost:7902 (`admin` / `admin`) |
| Mail (maildev) | http://localhost:7984 |
| S3 | http://localhost:7986 |

- Postgres and S3 keep their data in memory: `make e2e-up` starts empty.
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
- `createUser()` (`helpers/keycloak.ts`) signs a new Keycloak user up, for a
  test that changes what an account owns: claiming an inbox send attaches
  every later send to that address.
- `waitForMail()` (`helpers/mail.ts`) reads maildev. Tests run in parallel
  and share mailboxes: find your email by a unique title in its body
  (`uniqueTitle()`), or by an address only your test uses.
- `makeFile()` writes random bytes; compare a download with
  `downloadedBytes(download)`.
- Select by role and visible text, as a user would. The app has no
  `data-testid`. When the sidebar repeats a name, scope the locator to the
  page's own list.

## What is covered

| File | Flows |
|---|---|
| `transfer-link.spec.ts` | Link transfer, anonymous download (bytes compared), history; single-use link closing after download |
| `transfer-confidential.spec.ts` | Key in the fragment; key prompt without it (malformed key refused); confidential email keeps the key out of the invitation |
| `transfer-email.spec.ts` | Invitations to two recipients, personal links, download receipt to the sender, recipient in the history; recipient input validation |
| `transfer-manage.spec.ts` | Rename (and cancel), sidebar search, deactivate, delete permanently; another agent cannot open the transfer |
| `deposit-space.spec.ts` | Space creation, deposit by someone without an account (one-time code by email), receipt and notification emails, unscanned-file confirmation and download; deposit token is no capability; wrong code; closed space |
| `inbox.spec.ts` | Anonymous send to an agent, claim refused to another account, claim with sign-in on the way, later sends attached at once, inbox page; address outside the instance pattern |
| `public-pages.spec.ts` | Landing, language remembered, unknown links, sign-in error page, signed-out redirect, sign out |

Not covered yet: the antivirus (infected, scan errors: needs the file-scanner
stack), Drive import, the validity choice, `Retry sending` (needs a failing
SMTP), the Django admin, the mobile layout.
