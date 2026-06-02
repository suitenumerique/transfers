# Transferts backend

Django + DRF service that owns the data model, API, S3 storage,
authentication and Celery jobs. Single Django app: `core`.

## Layout

```
core/
├── api/
│   ├── viewsets/      # DRF ViewSets (one per resource)
│   ├── serializers.py
│   └── permissions.py
├── authentication/    # OIDC (ProConnect) integration
├── management/
│   └── commands/      # Custom manage.py commands
├── migrations/
├── services/          # Stateless helpers — S3, email, sweep
├── tasks.py           # Celery tasks
├── models.py          # TransferDraft, Transfer, TransferFile, TransferEvent, TransferRecipient, User
├── enums.py
└── tests/
```

## Viewsets

| File              | Resource           | Notable actions |
|-------------------|--------------------|-----------------|
| `draft.py`        | `TransferDraft`    | `add-file`, `sign-part`, `complete-upload`, `remove-file`, `abort`, `finalize` |
| `transfer.py`     | `Transfer`         | list/retrieve, `deactivate`, `resend-invitations` |
| `download.py`     | Public download    | Token-gated; serves presigned URLs to recipients |
| `user.py`         | Current user       | OIDC profile bridge |
| `config.py`       | Frontend config    | Public runtime config (Drive URL, max sizes…) |

## Services

- `services/s3.py` — boto3 client + multipart upload helpers. Two-tier
  API (raise vs best-effort).
- `services/s3_sweep.py` — orphan sweep orchestration, shared by the
  management command and the daily Celery task.
- `services/email.py` — recipient invitation rendering and SMTP send.

## Celery tasks (`tasks.py`)

- `expire_transfers_task` — flips `ACTIVE → EXPIRED`, deletes S3 files,
  emits audit events.
- `sweep_orphan_s3_storage_task` — daily safety net (`--min-age=24h`).
- `cleanup_abandoned_drafts_task` — drops drafts older than 24 h.
- `import_drive_file_task` — server-side stream from Drive into S3.
- `send_recipient_invitations_task` — email mode invitations + retry.

## Management commands (`management/commands/`)

- `clean_orphan_s3_objects` — manual sweep (operator tool, supports
  `--dry-run`).
- `seed_transfers` — generate fixtures for local development.
- `create_bucket`, `drop_all_tables`, `print_users`, `send_mail`,
  `createsuperuser` — utility scripts.

## Further reading

- [`../../docs/S3.md`](../../docs/S3.md) — S3 architecture, lifecycle,
  cleanup, locks, sweep, ops gotchas.
- [`../../README.md`](../../README.md) — project setup (`make
  bootstrap`, services, ports, La Suite Drive integration).
