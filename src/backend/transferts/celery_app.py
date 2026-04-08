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
