# Transfers

Sovereign file transfer service for La Suite territoriale.

Initially forked from [suitenumerique/messages](https://github.com/suitenumerique/messages).

## Stack

- **Backend**: Django + DRF, PostgreSQL, Celery/Redis, S3 (RustFS in dev)
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
(`agent@collectivite.fr` / `transferts`). Dev runs the real OIDC flow against a
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
carry the Transferts wordmark in the header and no footer logo.

| Variable | Effect |
|---|---|
| `DJANGO_EMAIL_LOGO_IMG` | Absolute URL of the header logo. Empty ⇒ the shipped Transferts wordmark. A custom logo is rendered 40px high at its natural width. |
| `DJANGO_EMAIL_FOOTER_LOGOS` | JSON list of footer logos, e.g. `[{"url":"https://…/rf.png","alt":"République Française","width":80,"height":44}]`. `width`/`height` are CSS px and optional. Empty ⇒ no footer logo (never a broken image). |
| `DJANGO_EMAIL_FROM` | Sender address (default `transferts@example.com`). |
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

## Background jobs (Celery beat)

Schedule is defined in `src/backend/transferts/celery_app.py`.

| Task | Cadence | Effect |
|---|---|---|
| `expire_transfers_task` | hourly (3600 s) | Flips `ACTIVE → EXPIRED` past `expires_at`, deletes S3 files |
| `cleanup_abandoned_drafts_task` | every 6 h (21600 s) | Drops drafts older than 24 h |
| `sweep_orphan_s3_storage_task` | daily (86400 s) | Safety net — should report 0; non-zero signals a leak in a per-row path |
| `send_recipient_invitations_task` | on-demand | Triggered by `finalize` (email mode) and `resend` |

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
| `TRANSFERTS_FRONTEND_TRUSTED_PROXIES` | _(empty: trust no proxy)_ | Space-separated CIDR list of the proxies whose `X-Forwarded-For` sets the client IP. On Scalingo, set `private_ranges`: the routers sit on private addresses that are not published, and the container port is only reachable through them. Do not use `private_ranges` where untrusted machines share the private network. **Unset on Scalingo, the audit log records the router's address instead of the user's.** |
| `DJANGO_ADMIN_IP_ALLOWLIST` | `0.0.0.0/0 ::/0` (everyone) | Space-separated CIDR list of the client IPs admitted on the admin URL; Caddy answers 403 to the others. Leave it unset to keep the admin open — an empty value admits no one. |
| `TRANSFERTS_FRONTEND_BACKEND_SERVER` | `localhost:8000` | `host:port` of the Django backend Caddy proxies `/api/*`, `/static/*` and the admin URL to. |

`make test-front-distroless` builds the production image and checks all
of this against it (allow and deny, spoofed headers, trusted proxies);
the CI runs it.

## La Suite integrations

### Drive (file picker)

Instances can optionally allow users to attach files from a [Drive](https://github.com/suitenumerique/drive) instance. When enabled, an "Attach from Drive" button appears in the transfer form. Files are downloaded client-side (using the user's Drive session) and uploaded through the regular multipart flow — no reference to Drive is stored.

**Transferts side** — set these environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `DRIVE_BASE_URL` | Yes | _(empty — feature disabled)_ | Base URL of the Drive instance |
| `DRIVE_SDK_URL` | No | `/sdk` | Path (or absolute URL) to the Drive SDK endpoint |
| `DRIVE_API_URL` | No | `/api/v1.0` | Path (or absolute URL) to the Drive API |
| `DRIVE_APP_NAME` | No | `Drive` | Display name shown in UI labels |

**Drive side** — the Drive instance must allow the Transferts origin:

```env
CORS_ALLOWED_ORIGINS=[..., "https://transferts.example.gouv.fr"]
SDK_CORS_ALLOWED_ORIGINS=[..., "https://transferts.example.gouv.fr"]
CORS_ALLOW_CREDENTIALS=True
```

Both CORS lists are required: `CORS_ALLOWED_ORIGINS` covers the HTTP fetch to download file bytes, `SDK_CORS_ALLOWED_ORIGINS` covers the postMessage channel used by the picker SDK.

## License

MIT
