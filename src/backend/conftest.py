"""Root conftest for pytest."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "transfers.settings")
os.environ.setdefault("DJANGO_CONFIGURATION", "Test")

from configurations.importer import install

install(check_options=False)
