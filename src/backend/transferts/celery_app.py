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
    "record-expired-transfers": {
        "task": "core.tasks.record_expired_transfers_task",
        "schedule": 3600.0,  # Every hour
    },
    "delete-expired-transfer-files": {
        "task": "core.tasks.delete_expired_transfer_files_task",
        "schedule": 86400.0,  # Daily
    },
    "cleanup-abandoned-uploads": {
        "task": "core.tasks.cleanup_abandoned_uploads_task",
        "schedule": 21600.0,  # Every 6 hours
    },
}
