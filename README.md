# Transferts

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

## License

MIT
