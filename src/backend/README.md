# Transferts backend

Django + DRF service that owns the data model, API, S3 storage,
authentication and Celery jobs. Single Django app: `core`.

## Layout

```
core/
├── api/
│   ├── viewsets/      # DRF ViewSets (one per resource)
│   ├── serializers.py
│   ├── permissions.py
│   └── utils.py
├── authentication/    # OIDC (ProConnect) integration
├── management/
│   └── commands/      # Custom manage.py commands
├── migrations/
├── services/          # Stateless helpers — S3, email, sweep
├── templates/         # Email templates (recipient invitation)
├── templatetags/      # Custom template filters (humanize_size)
├── tests/
├── admin.py
├── apps.py
├── enums.py
├── factories.py       # Test/seed factories
├── middlewares.py     # XForwardedForMiddleware
├── models.py          # TransferDraft, Transfer, TransferFile, TransferEvent, TransferRecipient, User
├── tasks.py           # Celery tasks
└── urls.py            # API routing
```

## Viewsets

| File              | Resource           | Notable actions |
|-------------------|--------------------|-----------------|
| `draft.py`        | `TransferDraft`    | `add-file`, `sign-part`, `complete-upload`, `remove-file`, `abort`, `finalize` |
| `transfer.py`     | `Transfer`         | list/retrieve, `deactivate`, `resend`, `events` |
| `download.py`     | Public download    | Token-gated; serves presigned URLs to recipients |
| `user.py`         | Current user       | OIDC profile bridge |
| `config.py`       | Frontend config    | Public runtime config (Drive URL, max sizes…) |

## Endpoints

All paths are prefixed by `/api/{API_VERSION}/` (e.g. `/api/v1.0/`).

| Method | Path | Description |
|---|---|---|
| POST | `drafts/add-file/` | Open or extend a draft with a new file |
| POST | `drafts/{id}/sign-part/` | Presigned URL for a chunk |
| POST | `drafts/{id}/complete-upload/` | Close the MPU for one file |
| POST | `drafts/{id}/remove-file/` | Detach a file from the draft |
| POST | `drafts/{id}/abort/` | Tear the whole draft down |
| POST | `drafts/{id}/finalize/` | Promote draft to `Transfer` |
| GET | `drafts/{id}/` | Draft detail (used by the Drive import poller) |
| GET | `transfers/` | Paginated list of the caller's transfers |
| GET | `transfers/{id}/` | Owner detail |
| POST | `transfers/{id}/deactivate/` | Manual deactivation |
| POST | `transfers/{id}/resend/` | Retry failed recipient invitations |
| GET | `transfers/{id}/events/` | Audit log |
| GET | `users/me/` | Current OIDC user |
| GET | `downloads/{public_token}/` | Public transfer view (no auth) |
| GET | `downloads/{public_token}/files/{file_id}/download/` | Presigned redirect to file bytes |
| GET | `config/` | Frontend runtime config |

## Services

- `services/s3.py` — boto3 client + multipart upload helpers. Two-tier
  API (raise vs best-effort).
- `services/s3_sweep.py` — orphan sweep orchestration, shared by the
  management command and the daily Celery task.
- `services/email.py` — recipient invitation rendering and SMTP send.

## Celery tasks (`tasks.py`)

### Scheduled (Celery beat)

Schedule defined in `transferts/celery_app.py`. See also the
[Background jobs table](../../README.md#background-jobs-celery-beat)
in the root README.

- `expire_transfers_task` — flips `ACTIVE → EXPIRED`, deletes S3 files,
  emits audit events.
- `cleanup_abandoned_drafts_task` — drops drafts older than 24 h.
- `sweep_orphan_s3_storage_task` — daily safety net (`--min-age=24h`).

### Triggered on demand

- `import_drive_file_task` — enqueued by `add_file` when a `source_url`
  is provided. Streams the file server-side from Drive into S3.
- `send_recipient_invitations_task` — enqueued by `finalize` (email
  mode) and `resend`. Only touches recipients with `email_sent_at IS
  NULL`, so calling it again is the natural retry path. Stamps
  `notifications_completed_at` on the transfer at the end of every
  run; the frontend polls this field to leave its "sending…" state.
  The `resend` viewset action resets `notifications_completed_at` to
  `NULL` so the polling round can detect the new completion
  timestamp.

## Concurrency — locking on `TransferDraft`

A `TransferDraft` is mutated by several paths that can race: the
browser uploading chunks, the user clicking "Finalize" or "Cancel",
the abandoned-drafts sweep landing at the wrong moment. To keep these
paths from corrupting each other, every mutating path takes a row-level
lock on the draft before reading or modifying it.

**Invariant.** Any code path that mutates a `TransferDraft` (or its
files) must take a row-level lock on the draft first.

The canonical helper is `_get_locked_draft(pk)` in
`viewsets/draft.py` — `SELECT ... FOR UPDATE` over the owner-scoped
queryset. Six sites use it:

| Site | Reason for the lock |
|---|---|
| `add_file` (only when a `draft_id` is given — first call creates the draft) | Cumulative size/count guards must read the current totals before allowing the new file |
| `complete_upload` | Two operations on the same file must serialize (e.g. user retry) |
| `remove_file` | Concurrent finalize must not race against a remove |
| `abort` | Concurrent finalize must not promote files we're tearing down |
| `finalize` | Reparenting must observe a consistent set of files |
| `cleanup_abandoned_drafts_task` (`tasks.py`) | Re-fetched per draft under `select_for_update().get(...)` so a finalize landing during the sweep wins |

A new mutating call site must use the helper or justify why it doesn't.

What is intentionally **not** locked:

- Read paths (`sign_part`, `retrieve`) — the worst that happens on a
  race is a presigned URL for a file that's about to be aborted, which
  the caller will fail to use; no data corruption.
- Public download endpoints — they read `Transfer`, not
  `TransferDraft`, and have their own access checks.

## Management commands (`management/commands/`)

- `clean_orphan_s3_objects` — manual sweep (operator tool, dry-run by
  default — pass `--apply` to actually delete).
- `seed_transfers` — generate fixtures for local development.
- `create_bucket`, `drop_all_tables`, `print_users`, `send_mail`,
  `createsuperuser` — utility scripts.

## Further reading

- [`../../docs/S3.md`](../../docs/S3.md) — S3 architecture, lifecycle,
  cleanup, sweep, ops gotchas.
- [`../../README.md`](../../README.md) — project setup (`make
  bootstrap`, services, ports, La Suite Drive integration).
