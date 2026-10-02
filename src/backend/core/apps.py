"""Transfers core application."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration class for the transfers core app."""

    name = "core"
    app_label = "core"
    verbose_name = "Transfers core"
