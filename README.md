# Transfers

Sovereign file transfer service for La Suite territoriale.

Initially forked from [suitenumerique/messages](https://github.com/suitenumerique/messages).

## Stack

- **Backend**: Django + DRF, PostgreSQL, Celery/Redis, S3 (RustFS in dev)
- **Frontend**: React (Next.js)
- **Auth**: ProConnect via OIDC

## Development

```bash
make bootstrap
```

Services:
- Frontend: http://localhost:8900
- API: http://localhost:8901
- Admin: http://localhost:8901/admin
- Mail: http://localhost:8904
- S3 Console: http://localhost:8907

## Configurable limits

| Setting | Default | Effect |
|---|---|---|
| `TRANSFER_MAX_FILE_SIZE` | 20 GiB | Cap per file |
| `TRANSFER_MAX_TOTAL_SIZE` | 20 GiB | Cap on the sum of files in a transfer |
| `TRANSFER_MAX_FILES_PER_TRANSFER` | 20 | Cap on file count per transfer |
| `TRANSFER_EXPIRY_CHOICES` | `1,7,30` | Expiry options offered in the UI (days) |
| `TRANSFER_DEFAULT_EXPIRY_DAYS` | 1 | Default expiry; must be in `TRANSFER_EXPIRY_CHOICES` |

Recipient count in email mode is hard-capped at 50 (in the serializer).

## Configuration

S3 / storage:

| Variable | Effect |
|---|---|
| `AWS_S3_ENDPOINT_URL` | S3 endpoint as seen from the backend |
| `AWS_S3_DOMAIN_REPLACE` | Hostname rewritten into presigned URLs (dev: backend sees `objectstorage:9000`, browser sees `localhost:8906`) |
| `AWS_S3_ACCESS_KEY_ID` / `AWS_S3_SECRET_ACCESS_KEY` | IAM credentials |
| `AWS_S3_REGION_NAME` | Region (default `us-east-1`) |
| `AWS_S3_SIGNATURE_VERSION` | `s3v4` by default |
| `TRANSFERS_BUCKET_NAME` | Bucket name |
| `TRANSFER_PRESIGNED_URL_EXPIRY` | Presigned URL TTL in seconds (default 600) |
| `TRANSFER_CHUNK_SIZE` | Multipart chunk size (default 25 MiB) |
| `TRANSFER_UPLOAD_PARALLELISM` | Concurrent part uploads (default 4) |

For IAM permissions required on the bucket, see [`docs/S3.md`](docs/S3.md#iam-permissions-on-the-bucket).

## Background jobs (Celery beat)

Schedule is defined in `src/backend/transferts/celery_app.py`.

| Task | Cadence | Effect |
|---|---|---|
| `expire_transfers_task` | hourly (3600 s) | Flips `ACTIVE → EXPIRED` past `expires_at`, deletes S3 files |
| `cleanup_abandoned_drafts_task` | every 6 h (21600 s) | Drops drafts older than 24 h |
| `sweep_orphan_s3_storage_task` | daily (86400 s) | Safety net — should report 0; non-zero signals a leak in a per-row path |
| `send_recipient_invitations_task` | on-demand | Triggered by `finalize` (email mode) and `resend` |

## Reverse proxy and `X-Forwarded-For`

The audit log records the client IP. It is read from `X-Forwarded-For`
by `XForwardedForMiddleware` (`src/backend/core/middlewares.py`), which
takes the **rightmost** entry — the IP appended by the trusted edge
proxy (Scalingo's router on production). The leftmost entry is
client-controlled and spoofable.

In production the request chain is:

```
Client → Edge router (Scalingo) → HAProxy → Caddy → Gunicorn
```

For this to work, **Caddy must propagate the incoming `X-Forwarded-For`
header as-is**, not overwrite it. `src/frontend/caddy/Caddyfile`
sets:

```caddyfile
header_up X-Forwarded-For {http.request.header.x-forwarded-for}
```

If you change it to `{remote_host}`, Caddy overwrites the chain with
the address of its immediate peer (HAProxy, in the `10.0.0.x` range),
and the audit log loses the real client IP. The comment block above
the first `reverse_proxy` directive in the `Caddyfile` explains the
two-hop topology.

Set `USE_X_FORWARDED_FOR=True` in the production environment to
activate the middleware.

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
