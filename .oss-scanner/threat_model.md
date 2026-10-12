# Threat model

## What this project does and where untrusted input enters

Transfers is the file transfer service of La Suite territoriale, a French
government platform (ANCT). Agents of French local authorities sign in and
send files to anyone: a recipient gets a link, opens a public download page
and needs no account. Every file is encrypted in the agent's browser before
upload (AES-GCM, `docs/ENCRYPTION.md`). In the normal mode the browser also
posts the key to the backend, which serves it to whoever holds the link. In
confidential mode the key stays in the URL fragment and never reaches the
server. An antivirus scanner (suitenumerique/file-scanner, a separate
service) checks the files it can, and the download of a file sent for
scanning stays closed until it answers. Some files are not scanned and stay
downloadable with a "not scanned" notice: `SKIPPED` (confidential transfers,
whose key never reaches us, or scanning disabled), `TOO_LARGE` (over
`SCAN_MAX_FILE_SIZE`) and `UNSCANNABLE` (the scanner could not read it).

The backend is Django 5 with Django REST Framework, in `src/backend`, with
Celery tasks in `src/backend/core/tasks.py`. The frontend is a Vite and React
single-page application in `src/frontend/src`, with no server rendering. The
decryption runs in a Service Worker, `src/frontend/public/sw.js`, which
streams the files from S3 through `/_dl/`. Caddy serves the frontend and
proxies `/api/*` to the backend (`src/frontend/caddy/Caddyfile`).

Actors: anonymous visitors who hold a download link; authenticated agents (an
OIDC session through ProConnect, `docs/authentication.md`) who own transfers
and drafts; the file scanner, which calls back a webhook; Django staff (the
admin, behind an IP allowlist at Caddy); the operators.

Entry points, most exposed first:

- The public download, `src/backend/core/api/viewsets/download.py`. The
  `public_token` in the link is the only capability: whoever holds it reads
  the transfer while it is active. `?r=<token>` names the recipient for the
  history and the download receipt, and grants nothing. `?resume=<token>` is
  a `TimestampSigner` value over `<transfer id>:<file id>` that lets an
  interrupted download finish during the purge grace of a one-shot transfer
  (`_resume_token_valid`). The view hands out a presigned S3 URL
  (`core/services/s3.py`, `sign_download_url`) only for a file whose scan
  answered CLEAN or a scan-exempt status.
- The scanner webhook, `src/backend/core/api/viewsets/webhook.py`. It is
  `AllowAny` with no authentication class. A per-file secret, minted when the
  file is submitted and echoed by the scanner in the query string, is
  compared in constant time. Only a PENDING file accepts a verdict, so a
  terminal verdict is final. Treat the endpoint as reachable by an attacker
  who has the network but not the secret.
- The login, `src/backend/core/authentication/` on top of django-lasuite's
  OIDC backend, and the entitlements gate, `src/backend/core/entitlements/`.
  At login and on every upload action
  (`core/api/permissions.py`, `DraftUploadEntitlementPermission`) the
  DeployCenter backend asks Espace Opérateur whether the agent's
  organisation may use the service. It fails closed when the service is
  unreachable and nothing is cached.
- The agent API, `src/backend/core/api/viewsets/draft.py` and
  `transfer.py`. A draft is an upload session: add a file, sign the parts of
  a multipart upload, complete it, finalize the draft into a transfer with its
  recipients. Every queryset is filtered on `owner=request.user`; that filter
  is the whole authorization model. `finalize` sends invitation emails whose
  title and file names the agent chose (`core/services/email.py`).
- The Drive import. A file added with a `source_url` is fetched server-side by
  `import_drive_file_task` in `core/tasks.py`, encrypted with the draft key and
  uploaded to S3. The URL comes from the agent's request. A fetch that leaves
  the configured Drive host or reaches a private address is a finding.
- The calls to the scanner, `submit_scan_task` in `core/tasks.py`, signed with
  an Ed25519 JWT bound to the body hash (`core/services/scan_auth.py`). The
  scanner fetches the file through a presigned URL.
- The web client, `src/frontend/src`, and the Service Worker. The download
  page renders a title, file names and a sender name that an agent wrote.
- The Caddyfile: trusted proxies and the client IP, the CSP and security
  headers, the admin allowlist, the SPA fallback.

## Components that matter most / least

Most important, report findings here first:

- `src/backend/core/api/viewsets/download.py`: the only code an anonymous
  visitor reaches with data behind it, and the scan gate.
- `src/backend/core/api/viewsets/webhook.py` and `core/enums.py`
  (`ScanStatus`): a forged or replayed verdict releases a file.
- `src/backend/core/api/viewsets/draft.py`, `transfer.py` and `user.py`, and
  `core/api/permissions.py`: who can read or change a transfer, a draft or a
  file.
- `src/backend/core/authentication/` and `src/backend/core/entitlements/`.
- `src/backend/core/tasks.py`: the Drive import, the scan submission and the
  S3 cleanup.
- `src/backend/core/services/s3.py` and `core/services/encryption.py`: which
  object a presigned URL names, and how the server-side key is used.
- `src/frontend/public/sw.js` and the download page in
  `src/frontend/src/features/transfers/`.

Less important, but still in scope: `core/services/email.py` and the email
templates, `core/admin.py`, the management commands, the rest of
`src/frontend/src`, `src/frontend/caddy/Caddyfile`.

Out of scope as a target, do not report findings here: Keycloak and
`src/keycloak/` (the development OIDC realm), the file scanner itself (its own
repository), `core/migrations/` (schema history), the test suites
(`core/tests/`, `core/factories.py`, `src/frontend/**/*.test.*`), the
translation files, `bin/`, `compose.yaml`, `Makefile`, `env.d/`; third-party
code in `/opt/venv`, `/opt/s3`, `/opt/python`, `/usr/local/lib/node_modules`
and `node_modules`.

## How to exercise it

The image for this scan places the checkout at `/src`. The backend is at
`/src/src/backend` and the frontend at `/src/src/frontend`.
`DJANGO_CONFIGURATION=Test` and the database, Redis and S3 variables are
already set.

PostgreSQL 17, Redis and an S3 endpoint (moto, on port 9000, with the
`transfers` bucket) run in the image. The first bash shell starts them and
exports `OSS_SCANNER_SERVICES_STARTED=1`; shells it spawns inherit that and
skip the start, so after `svcctl stop` run `svcctl start` yourself.
`BASH_ENV` only reaches bash, so a `sh` or `#!/bin/sh` script must run
`svcctl start` itself. Use `svcctl start`, `svcctl stop` and `svcctl status`
to control them, and `svcctl psql -d transfers` to inspect the already
migrated `transfers` database. moto keeps its bucket in memory, so an object
does not survive a restart of the container. Its log is
`/var/log/moto_server.log`.

The backend environment is `/opt/venv/backend`; it is on `PATH` and
`VIRTUAL_ENV` names it, so a bare `python`, `pytest`, `ruff` or
`uv pip install` acts on it.

Run the backend tests:

```sh
cd /src/src/backend
pytest --reuse-db --no-cov
```

Add `-n 2` to use both CPUs of the scan machine. Add `--create-db` after a
model change. Factories are in `core/factories.py`; the fixtures in
`core/tests/conftest.py` give an authenticated client, an in-process moto
bucket (`live_s3_bucket`) and files in every upload state. Tests named
`test_api_*.py` show how to call each endpoint; `test_api_webhook.py` and
`test_scan_auth.py` cover the scanner contract.

Run the development server:

```sh
cd /src/src/backend
python manage.py runserver --nostatic 0.0.0.0:8000
```

`--nostatic` leaves `/static/` to WhiteNoise, which serves the files
collected in `/data/static` at build time, as in production. The swagger UI
is at `/api/v1.0/swagger/`. The OIDC provider is not running: to act as an
agent against `runserver`, create a user and a session with
`python manage.py shell` (or use the test client), and send the session
cookie with the CSRF token. The scanner is not running either; a test can post its callback to
`/api/v1.0/webhooks/scan-result/` directly.

Run the frontend checks, all offline:

```sh
cd /src/src/frontend
npm run test
npm run lint
npm run ts:check
```

`npm run build` also works; `src/frontend/dist` is not built in the image.
Caddy is not in the image (`src/frontend/Dockerfile` builds it); read the
Caddyfile statically.

## How you rate severity

Rate the impact on the confidentiality of somebody else's files first. An
authority sends documents through this service that must reach only the
people it chose.

Critical: remote code execution; authentication bypass; reading a transfer,
a draft or a file without its `public_token` and without owning it; a scan
verdict that an attacker without the file's webhook secret can set, or any
path that makes a PENDING or INFECTED file downloadable; the server learning
the key of a confidential transfer; a leak of `DJANGO_SECRET_KEY` (it signs
sessions and resume tokens), the OIDC client secret, the scanner signing key
or the DeployCenter API key that an attacker can reach.

High: an authenticated agent reads or changes a transfer, a draft or a file
that is not theirs (an IDOR); a stored cross-site scripting that runs in the
application's origin, including through a file name, a title or a sender
name; SQL injection, including after authentication; server-side request
forgery that reaches our internal network, through the Drive import or
anything else; cross-site request forgery on a state-changing endpoint; a
bypass of the entitlements gate at login or on upload; a presigned URL that
names an object outside the transfer it was issued for; a reopened transfer
that its owner deactivated or that expired.

Medium: a leak of metadata to someone who is not the owner (titles, file
names, recipient addresses, the transfer history); content injection in the
invitation or receipt emails beyond the text fields an agent controls; sending
invitations past the per-agent limits; a missing rate limit on an
unauthenticated path; a denial of service that one anonymous request causes.

Low: a hardening gap with no demonstrated impact; a missing security header;
a missing rate limit on an authenticated endpoint; a crash that only the
caller's own session feels.

Rules we apply on top:

- A finding that needs a Django staff account is one level lower. Staff are
  operators, the admin sits behind an IP allowlist, and an operator who
  reads the logs can read the database.
- A finding that needs database, S3 or host access is not a finding.
- Show the path from the untrusted input to the effect.
- A report that depends on a development value from `env.d/development/` in
  production is not a finding.

Not a finding: anything that exists only under the `Build`, `Development`,
`DevelopmentMinimal`, `Test` or `ContinuousIntegration` classes in
`src/backend/transfers/settings.py`; report against `Production` and the
classes that inherit it, `Staging` and `PreProduction`. Reflected content in a
JSON response, because the client is a single-page application.

## Anything to leave alone

- This image runs `DJANGO_CONFIGURATION=Test`, the same configuration CI
  uses: the MD5 password hasher, `USE_SWAGGER=True`, a dummy
  `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS=*`, a superuser database role
  named `user` with password `pass`, `fsync=off`, and the development values
  of the S3 and OIDC keys.
- Every secret in `env.d/development/*.defaults`, `src/keycloak/` and
  `compose.yaml` is a public development value, not a leak.
- The image uses PostgreSQL 17 and moto. Development and CI use PostgreSQL
  16.6 and rustfs (`compose.yaml`). This difference is intentional.
- The link is a bearer capability by design. Anyone who holds a
  `public_token` reads an active transfer, and in the normal mode the API
  serves the decryption key to that visitor (`DownloadTransferSerializer`).
  The normal mode protects the files at rest in S3, not from link holders.
  Only confidential mode keeps the key off the server.
- `?r=` is attribution only. A missing, stale or foreign recipient token
  must not block a download.
- `SKIPPED`, `TOO_LARGE` and `UNSCANNABLE` files are downloadable on purpose
  and the page says they were not scanned. Report only a path that releases a
  PENDING or INFECTED file, or that makes an unscanned file pass as CLEAN.
- The webhook secret and the recipient and resume tokens travel in query
  strings, and Caddy logs full URLs on purpose: the people who read those
  logs can read the database. Report an exposure of these values elsewhere.
- The `Static` entitlements backend, the default, lets everyone in;
  production sets `ENTITLEMENTS_BACKEND` to the DeployCenter backend. When
  DeployCenter is unreachable, a cached answer is served for up to 24 hours
  (`stale_timeout`), except after a 401 or a 403. Both are design choices.
- `OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION` is off by default and only
  meant for a one-off migration. A takeover that needs it on is low.
- A download receipt goes out once per recipient (`download_notified_at`); a
  link scanner that opens the link counts as an open.
- `ruff`, `pylint`, `eslint` and `tsc` run in CI. Do not report their
  opinions.
- A dependency CVE with no reachable call path in this code is not wanted.

## How reports and patches should look

Submit one finding per report, with an input that reproduces it: a `curl`
command against `runserver`, or a failing `pytest` test under
`src/backend/core/tests` that uses the factories in `core/factories.py` and
the fixtures in `core/tests/conftest.py`.

Include a patch as a diff. A backend patch must pass, from `src/backend`:

```sh
ruff check
ruff format --check
```

The line length is 88 characters (`src/backend/pyproject.toml`). A frontend
patch must pass `npm run lint` and `npm run ts:check`.

Send security questions outside this scan to security@suite.anct.gouv.fr,
per `SECURITY.md`.
