"""Transferts celery configuration."""

import os

from celery import Celery
from configurations.importer import install

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "transferts.settings")
os.environ.setdefault("DJANGO_CONFIGURATION", "Development")

install(check_options=True)

app = Celery("transferts")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "deactivate-expired-transfers": {
        "task": "core.tasks.deactivate_expired_transfers_task",
        "schedule": 3600.0,  # Every hour
    },
    "delete-pending-transfer-files": {
        "task": "core.tasks.delete_pending_transfer_files_task",
        "schedule": 3600.0,  # Every hour — up to ~1h of drift on the 6h default
    },
    "cleanup-abandoned-drafts": {
        "task": "core.tasks.cleanup_abandoned_drafts_task",
        "schedule": 21600.0,  # Every 6 hours
    },
    "sweep-orphan-s3-storage": {
        "task": "core.tasks.sweep_orphan_s3_storage_task",
        "schedule": 86400.0,  # Every 24 hours
    },
}
