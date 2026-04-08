"""Transferts core application."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration class for the transferts core app."""

    name = "core"
    app_label = "core"
    verbose_name = "Transferts core"

    def ready(self):
        import core.signals  # noqa: F401
