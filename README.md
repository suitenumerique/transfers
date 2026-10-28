# Transfers

Sovereign file transfer service for La Suite territoriale.

Initially forked from [suitenumerique/messages](https://github.com/suitenumerique/messages).

## Stack

- **Backend**: Django + DRF, PostgreSQL, Dramatiq/Redis, S3 (RustFS in dev)
- **Frontend**: React (Vite + TanStack Router)
- **Auth**: ProConnect via OIDC (a local Keycloak stands in for it in dev)

## Development

```bash
make bootstrap
```

Services:
- Frontend: http://localhost:8980
- API: http://localhost:8981
- Admin: http://localhost:8981/admin
- Mail: http://localhost:8984
- S3 Console: http://localhost:8987
- Keycloak (dev OIDC): http://localhost:8902 (`admin` / `admin`)

**Signing in:** open the frontend, click _Sign in_, and use a seeded test user
(`user1@example.local` / `user1`). Dev runs the real OIDC flow against a
local Keycloak — no ProConnect needed. See [`docs/authentication.md`](docs/authentication.md).

## Configurable limits

| Setting | Default | Effect |
|---|---|---|
| `TRANSFER_MAX_FILE_SIZE` | 20 GiB | Cap per file |
| `TRANSFER_MAX_TOTAL_SIZE` | 20 GiB | Cap on the sum of files in a transfer |
| `TRANSFER_MAX_FILES_PER_TRANSFER` | 20 | Cap on file count per transfer |
| `TRANSFER_EXPIRY_CHOICES` | `1,7,30` | Expiry options offered in the UI (days) |
| `TRANSFER_DEFAULT_EXPIRY_DAYS` | 1 | Default expiry; must be in `TRANSFER_EXPIRY_CHOICES` |
| `TRANSFER_PURGE_DELAY_HOURS` | 6 | Grace period between link closure and S3 deletion (one-shot links + expiry + manual deactivation) |
| `TRANSFER_CONFIDENTIAL_ENABLED` | `True` | Offer the "confidential transfer" toggle. `False` hides it and makes finalize reject `confidential`; existing confidential transfers stay downloadable |
| `TRANSFER_DOWNLOAD_RECEIPT_DELAY` | 3600 | Seconds after a recipient's first download before the sender's receipt goes out when that recipient hasn't taken every file (see Delivery receipts) |

Recipient count in email mode is hard-capped at 50 (in the serializer).

Abuse limits:

| Setting | Default | Effect |
|---|---|---|
| `THROTTLE_USER_OUTBOUND_RECIPIENTS` | `200/day` | Invitation emails one agent may trigger per sliding period, all transfers together (finalize answers 429 past it). `count/period` with period `minute`, `hour` or `day`; empty to disable |
| `API_DRAFT_ADD_FILE_THROTTLE_RATE` | `300/hour` | Files an agent may attach (browser uploads and Drive imports) |
| `API_TRANSFER_RESEND_THROTTLE_RATE` | `30/hour` | Invitation re-sends per agent |
| `API_PUBLIC_DOWNLOAD_THROTTLE_RATE` | `1000/hour` | Download page + file URL calls per visitor IP (per user when signed in) |

Throttle counters live in the default cache (Redis in production).

## Receiving files (deposits)

People without an account can send files to an agent, two ways:

- **Deposit spaces.** An agent creates spaces (`/spaces`), each with a link
  `/d/<token>` they hand out. The space lives until the agent closes it;
  each deposit is kept for the space's retention.
- **Anonymous sends.** On `/send`, a visitor sends files straight to an
  agent's address, if it matches `INBOX_RECIPIENT_EMAIL_REGEX`.

Either way the depositor gives a name, an email and a subject, and proves
the email with a 6-digit code sent to it. The code opens an upload session
(`X-Deposit-Token`) for one deposit. The agent is emailed at each deposit,
the depositor gets a receipt. A deposit is an inbound transfer: only its
owner can open its link, and it is never confidential, since the owner
decrypts with the stored key and the antivirus reads it. An infected file
refuses the deposit; a file the antivirus could not check goes through,
and the agent must confirm before downloading it.

An anonymous send to an address nobody has claimed yet carries a claim
link: the agent signs in with ProConnect as that address and collects it.
That also records that this account reads the mailbox, so later sends to
it attach at once. Matching the identity email alone would not do: any
provider asserting the address would get the files (see
`docs/authentication.md`).

| Setting | Default | Effect |
|---|---|---|
| `DEPOSIT_MAX_TOTAL_SIZE` | 10 GiB | Cap on one deposit, all files together. A space can override it in the Django admin (`max_deposit_size`), nowhere else |
| `DEPOSIT_SPACE_RETENTION_CHOICES` | `7,30,90` | Days a space may keep its deposits for |
| `DEPOSIT_SPACE_DEFAULT_RETENTION_DAYS` | 30 | Default retention; must be in `DEPOSIT_SPACE_RETENTION_CHOICES` |
| `INBOX_RECIPIENT_EMAIL_REGEX` | _(empty: off)_ | Agent addresses an anonymous send may target, matched whole and case-insensitively, e.g. `[^@\s]+@([a-z0-9-]+\.)*gouv\.fr`. Empty hides `/send` |
| `INBOX_RETENTION_DAYS` | 30 | Days an anonymous send is kept |
| `DEPOSIT_OTP_TTL_SECONDS` / `DEPOSIT_OTP_MAX_ATTEMPTS` | 600 / 5 | Lifetime and wrong tries of a code |
| `DEPOSIT_SESSION_MAX_AGE` | 43200 | Seconds the upload session a code opens lasts; must cover the slowest full upload |
| `THROTTLE_DEPOSITS_PER_TARGET` | `30/day` | Deposits one space or one agent address may receive per sliding period (429 past it) |
| `THROTTLE_DEPOSIT_CODES_PER_EMAIL` | `20/day` | Codes one depositor address may be sent, from any IP; each allows `DEPOSIT_OTP_MAX_ATTEMPTS` guesses, so this bounds guessing per address |
| `THROTTLE_DEPOSITS_PER_DEPOSITOR` | `10/day` | Deposits one verified depositor email may make per sliding period |
| `API_DEPOSIT_CHALLENGE_THROTTLE_RATE` | `20/hour` | Code requests per IP |
| `API_DEPOSIT_CHALLENGE_EMAIL_THROTTLE_RATE` | `5/hour` | Code requests per depositor email, from any IP: bounds the mail one address can be sent |
| `API_DEPOSIT_VERIFY_THROTTLE_RATE` | `30/hour` | Code guesses per IP |
| `API_DEPOSIT_PUBLIC_THROTTLE_RATE` | `300/hour` | Deposit page loads per IP |

## Configuration

S3 / storage:

| Variable | Effect |
|---|---|
| `AWS_S3_ENDPOINT_URL` | S3 endpoint as seen from the backend |
| `AWS_S3_DOMAIN_REPLACE` | Hostname rewritten into presigned URLs (dev: backend sees `objectstorage:9000`, browser sees `localhost:8986`) |
| `AWS_S3_ACCESS_KEY_ID` / `AWS_S3_SECRET_ACCESS_KEY` | IAM credentials |
| `AWS_S3_REGION_NAME` | Region (default `us-east-1`) |
| `AWS_S3_SIGNATURE_VERSION` | `s3v4` by default |
| `AWS_STORAGE_BUCKET_NAME` | Bucket name |
| `TRANSFER_PRESIGNED_URL_EXPIRY` | Presigned URL TTL in seconds (default 600) |
| `TRANSFER_CHUNK_SIZE` | Multipart chunk size (default 25 MiB) |
| `TRANSFER_UPLOAD_PARALLELISM` | Concurrent part uploads (default 4) |

For IAM permissions required on the bucket, see [`docs/S3.md`](docs/S3.md#iam-permissions-on-the-bucket).

### Branding (notification emails)

No institutional identity ships with the code. The République Française
block, the La Suite territoriale logo and the `@suite-territoriale.fr`
sender are marks reserved to the French state and its operators, and this
project is open source — a self-hosted instance must not end up sending
them by default. Everything below is therefore deployment-supplied (the
same convention as [docs](https://github.com/suitenumerique/docs) and
[drive](https://github.com/suitenumerique/drive)); with nothing set, emails
carry the Transfers wordmark in the header and no footer logo.

| Variable | Effect |
|---|---|
| `DJANGO_EMAIL_LOGO_IMG` | Absolute URL of the header logo. Empty ⇒ the shipped Transfers wordmark. A custom logo is rendered 40px high at its natural width. |
| `DJANGO_EMAIL_FOOTER_LOGOS` | JSON list of footer logos, e.g. `[{"url":"https://…/rf.png","alt":"République Française","width":80,"height":44}]`. `width`/`height` are CSS px and optional. Empty ⇒ no footer logo (never a broken image). |
| `DJANGO_EMAIL_FROM` | Sender address (default `transfers@example.com`). |
| `TERMS_URL` | Terms-of-use link in the email footer (omitted when empty). |
| `HELP_URL` | Help link on the sidebar and the recipient page (hidden when empty). |

Point the image variables at **PNG** files hosted on a public URL: Gmail,
Outlook (desktop and web), Yahoo and iOS Mail do not render SVG in emails.
Supply 2x rasters sized to the `width`/`height` you declare for crisp
retina rendering.

## Delivery receipts (email mode)

Every recipient of an email-mode transfer gets the same public link plus a
personal `?r=<token>` (`TransferRecipient.token`). The download page and
the decryption Service Worker forward it on every call, so `LINK_OPENED`
and `FILE_DOWNLOADED` events carry a `recipient_id`. The transfer detail
folds those events into one `status` per recipient — `sending`, `failed`,
`sent`, `opened`, `downloaded` (+ `downloaded_file_count`) — which the
post-send summary and the transfer page render as icons. There is no
"received" state: the relay accepting a message says nothing about the
mailbox, and we don't do read tracking.

A link copied from the recipient page or the sender's page carries no
token, so activity through it stays anonymous in the history.

`notify_on_download` (checkbox on the form, email mode only) emails the
sender once per recipient: immediately once that recipient has downloaded
every file, or `TRANSFER_DOWNLOAD_RECEIPT_DELAY` seconds (default 3600)
after their first download if they stopped partway, reporting "n of N"
and which files were taken. Sent by `send_download_receipt_task`;
at-most-once via `TransferRecipient.download_notified_at`, so whichever
trigger fires first wins.

## Background jobs

Tasks run on Dramatiq, over a Redis Streams broker (`WORKER_BROKER_URL`,
Redis >= 7, with no eviction). `python worker.py` runs the worker and, as a
forked sidecar, the periodic scheduler: every worker runs one, and a Redis
lock lets a single one fire the schedule. The schedule is the `@cron`
decorators in `src/backend/core/tasks.py`. The queue dashboard is in the
Django admin, at `/admin/worker-dashboard/` (superusers only).

| Task | Cadence | Effect |
|---|---|---|
| `deactivate_expired_transfers_task` | hourly, at :00 | Flips transfers past `expires_at` to pending file deletion |
| `delete_pending_transfer_files_task` | hourly, at :15 | Wipes the S3 files of transfers past their grace period |
| `cleanup_abandoned_drafts_task` | every 6 h, at :30 | Drops drafts older than 24 h |
| `sweep_orphan_s3_storage_task` | daily, at 00:45 | Safety net — should report 0; non-zero signals a leak in a per-row path |
| `reap_stale_pending_scans_task` | every 5 min, from :02 | Re-submits scans whose result never came back |
| `send_recipient_invitations_task` | on-demand | Triggered by `finalize` (email mode) and `resend` |
| `send_deposit_notification_task` / `send_deposit_receipt_task` | on-demand | Triggered by a deposit's finalize |
| `purge_deposit_challenges_task` | daily, at 00:50 | Drops depositor codes and sessions that hold no upload, once past the upload session and the `THROTTLE_DEPOSIT_CODES_PER_EMAIL` period (25 h by default) |

`python worker.py --ping` is the worker's healthcheck: it sends a ping on a
queue only this container consumes and exits 0 once the answer comes back.

## End-to-end encryption

Senders can opt into client-side AES-256-GCM encryption by ticking the
"End-to-end encryption" checkbox on the transfer form. When enabled:

- A 256-bit key is generated in the sender's browser and embedded in
  the download URL fragment (after `#`). Browsers never transmit
  fragments, so the key never reaches the backend.
- Each upload chunk is encrypted in the browser before being PUT to S3
  via the existing presigned multipart flow. The backend stores
  ciphertext only — `TransferFile.size` is the on-S3 size,
  `TransferFile.plaintext_size` tracks the pre-encryption size for UI
  display.
- The recipient's browser registers a Service Worker (`/sw.js`) that
  intercepts the download URL, fetches the ciphertext, decrypts it
  chunk-by-chunk, and streams plaintext straight to the native
  download manager. Nothing transits through a Django worker; nothing
  buffers in RAM.
- Antivirus scanning is bypassed (we cannot scan what we cannot read).
  Files land as `scan_status=skipped` and recipients see no scan
  badge.

Two operational caveats:

- **Email mode + E2E**: the link we email out contains the key in its
  fragment, so every SMTP relay and mailbox provider on the way to the
  recipient sees it. The frontend warns the sender. For strict E2E,
  use link mode and hand the URL off via a side channel.
- **CORS on the S3 bucket**: the recipient's Service Worker fetches
  the presigned S3 URL cross-origin. The bucket must accept `GET`
  from the frontend's origin — see
  [`docs/S3.md`](docs/S3.md#cors-on-the-bucket-required-for-e2e). Non-E2E
  transfers don't need this (the browser follows a 302 redirect, which
  isn't CORS-gated).

The key is stored locally on the sender's device (`localStorage`,
keyed by transfer id) so the owner can rebuild the working link from
their dashboard. Clearing browser data drops that copy — the transfer
remains downloadable for anyone still holding the link.

## Reverse proxy, client IP and the admin allowlist

The audit log records the client IP, and the Django admin can be
restricted to an IP allowlist. Both rely on the client IP that Caddy
(`src/frontend/caddy/Caddyfile`, the production frontend image)
establishes: the TCP peer, unless that peer is a trusted proxy — then
the address in `X-Forwarded-For`, walked from the right to the first
one that is not a trusted proxy (`trusted_proxies_strict`). A prefix a
client writes into the header never wins. Caddy forwards that single
address to the backend as `X-Forwarded-For`, where
`XForwardedForMiddleware` (`src/backend/core/middlewares.py`, enabled
by `USE_X_FORWARDED_FOR=True`) sets `REMOTE_ADDR` from it.

In production the request chain is:

```
Client → Edge router (Scalingo) → HAProxy → Caddy → Gunicorn
```

| Variable | Default | Description |
|---|---|---|
| `TRANSFERS_FRONTEND_TRUSTED_PROXIES` | _(empty: trust no proxy)_ | Space-separated CIDR list of the proxies whose `X-Forwarded-For` sets the client IP. **Set it to your proxies' CIDRs, never to `private_ranges`**: a published container port is reached through a bridge gateway on a private address, so trusting that range lets any client set `X-Forwarded-For` and walk past the admin allowlist — `bin/smoke-test-front` covers exactly that. Left unset, `{client_ip}` is whatever connects to Caddy — HAProxy in the chain above, not the edge router, and behind a NAT the container's own gateway — so the audit log records that hop instead of the user and the allowlist filters on the wrong address. |
| `DJANGO_ADMIN_IP_ALLOWLIST` | `0.0.0.0/0 ::/0` (everyone) | Space-separated CIDR list of the client IPs admitted on the admin URL; Caddy answers 403 to the others. Leave it unset to keep the admin open — an empty value admits no one. It is compared against the `{client_ip}` the row above establishes, so narrowing this one while trusting no proxy filters on the proxy's address, not the user's. A 403 you did not expect: read Caddy's access log for that request and compare `client_ip` — the address that was matched — with the address you expect the client to have. If it is not the client's, the logged `X-Forwarded-For` shows the chain the proxy sent and therefore which hop was taken instead, and the row above needs your proxies' CIDRs. The two values differ whenever the chain has more than one hop, so that on its own proves nothing. |
| `TRANSFERS_FRONTEND_BACKEND_SERVER` | `localhost:8000` | `host:port` of the Django backend Caddy proxies `/api/*`, `/static/*` and the admin URL to. |

`make test-front-distroless` builds the production image and checks all
of this against it (allow and deny, spoofed headers, trusted proxies);
the CI runs it.

## La Suite integrations

### Drive (file picker)

Instances can optionally allow users to attach files from a [Drive](https://github.com/suitenumerique/drive) instance. When enabled, an "Attach from Drive" button appears in the transfer form. Files are downloaded client-side (using the user's Drive session) and uploaded through the regular multipart flow — no reference to Drive is stored.

**Transfers side** — set these environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `DRIVE_BASE_URL` | Yes | _(empty — feature disabled)_ | Base URL of the Drive instance |
| `DRIVE_SDK_URL` | No | `/sdk` | Path (or absolute URL) to the Drive SDK endpoint |
| `DRIVE_API_URL` | No | `/api/v1.0` | Path (or absolute URL) to the Drive API |
| `DRIVE_APP_NAME` | No | `Drive` | Display name shown in UI labels |
| `DRIVE_IMPORT_ALLOW_PRIVATE_NETWORKS` | No | `False` (`True` in Development) | Let server-side Drive imports reach private / loopback addresses. Leave off in production |

Server-side imports (`source_url`) are fetched by the worker, so they are
locked down: the URL must share the scheme and host of `DRIVE_BASE_URL`
(any `source_url` is refused while it is empty), redirects are followed by
hand, and every hop must resolve to a public address.

**Drive side** — the Drive instance must allow the Transfers origin:

```env
CORS_ALLOWED_ORIGINS=[..., "https://transferts.example.gouv.fr"]
SDK_CORS_ALLOWED_ORIGINS=[..., "https://transferts.example.gouv.fr"]
CORS_ALLOW_CREDENTIALS=True
```

Both CORS lists are required: `CORS_ALLOWED_ORIGINS` covers the HTTP fetch to download file bytes, `SDK_CORS_ALLOWED_ORIGINS` covers the postMessage channel used by the picker SDK.

## License

MIT
