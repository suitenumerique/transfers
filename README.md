# Transfers

Service de transfert de fichiers souverain pour La Suite territoriale.

Forked from [suitenumerique/messages](https://github.com/suitenumerique/messages).

## Stack

- **Backend**: Django + DRF, PostgreSQL, Celery/Redis, S3 (MinIO en dev)
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
