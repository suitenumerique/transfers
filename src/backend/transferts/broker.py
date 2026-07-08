"""Background-task broker configuration for Transferts.

Defines the single, process-wide broker — kept in this one module so swapping
the task backend stays localized. Every process (web, worker, scheduler) calls
:func:`configure` — from ``core.apps.CoreConfig.ready`` — so that:

* ``@register_task`` actors bind to the right broker at import time, and
* ``task.delay(...)`` from a request handler reaches Redis.

In production the broker is the custom :class:`~dramatiq_redis_streams.StreamsBroker`
(event-driven Redis Streams). In eager environments (tests, minimal dev) it is a
synchronous :class:`~core.tasks_helpers.EagerBroker`, so no Redis is required.
"""

import logging

from django.conf import settings

import dramatiq

logger = logging.getLogger(__name__)


class _SentryMiddleware(dramatiq.Middleware):
    """Report unhandled task exceptions to Sentry.

    Dramatiq has no first-party Sentry integration, so we wire one up: any
    exception that escapes a task is captured here before dramatiq retries or
    dead-letters the message.
    """

    # dramatiq's middleware API names this positional argument ``broker``.
    def after_process_message(self, broker, message, *, result=None, exception=None):  # pylint: disable=redefined-outer-name
        if exception is not None:
            import sentry_sdk  # pylint: disable=import-outside-toplevel

            sentry_sdk.capture_exception(exception)


def _make_broker():
    # Lazy imports so the eager path never pulls in redis/streams, and the
    # streams path never pulls in the stub broker.
    # pylint: disable=import-outside-toplevel
    if getattr(settings, "WORKER_EAGER", False):
        from core.tasks_helpers import EagerBroker

        return EagerBroker()

    from dramatiq_redis_streams import StreamsBroker

    instance = StreamsBroker(
        url=settings.WORKER_BROKER_URL,
        namespace=settings.WORKER_QUEUE_NAMESPACE,
    )
    if settings.SENTRY_DSN:
        instance.add_middleware(_SentryMiddleware())
    return instance


# Built once, at import. ``CoreConfig.ready`` imports this module before the task
# modules, so every ``@register_task`` actor binds to this broker; ``worker.py``
# hands the task CLI ``transferts.broker:broker``.
broker = _make_broker()
dramatiq.set_broker(broker)


def configure():
    """Return the process-wide broker (installed at import time).

    Kept as an explicit hook for ``CoreConfig.ready`` so the broker is set up
    before the task modules are imported.
    """
    return broker
