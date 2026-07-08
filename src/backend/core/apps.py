"""Transferts core application."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration class for the transferts core app."""

    name = "core"
    app_label = "core"
    verbose_name = "Transferts core"

    def ready(self):
        """Install the task broker and register all tasks.

        Configuring the broker *before* importing ``core.tasks`` guarantees the
        ``@register_task`` actors bind to the right broker. Importing the module
        here (rather than lazily) also runs the ``@cron_task`` decorators, so the
        ``manage.py crontab`` scheduler sees every schedule.

        Imports are local: they must not run at module-import time, only once the
        app registry is ready.
        """
        # pylint: disable=import-outside-toplevel
        import importlib

        from transferts import broker

        broker.configure()

        # Imported for its side effects — registers every task actor and cron
        # schedule on the broker.
        importlib.import_module("core.tasks")
