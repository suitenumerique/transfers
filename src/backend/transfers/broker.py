"""Background-task broker configuration for Transfers.

Defines the single, process-wide broker — kept in this one module so swapping
the task backend stays localized. Every process (web, worker, scheduler) imports
it from ``core.apps.CoreConfig.ready``, before the task modules, so that:

* actors bind to the right broker at import time, and
* ``task.send(...)`` from a request handler reaches Redis.

In production the broker is the custom :class:`~dramatiq_redis_streams.StreamsBroker`
(event-driven Redis Streams). In eager environments (tests, minimal dev) it is a
synchronous :class:`EagerBroker`, so no Redis is required.
"""

import logging

from django.conf import settings

import dramatiq
import sentry_sdk
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import Retries
from dramatiq.results import Results

logger = logging.getLogger(__name__)


class _SentryMiddleware(dramatiq.Middleware):
    """Report a task exception to Sentry once the message is given up on.

    Added before ``Retries``, so it runs after it and sees ``message.failed``:
    an attempt that will be retried sends no event.
    """

    # dramatiq's middleware API names this positional argument ``broker``.
    def after_process_message(self, broker, message, *, result=None, exception=None):  # pylint: disable=redefined-outer-name
        if exception is not None and message.failed:
            sentry_sdk.capture_exception(exception)


class EagerBroker(StubBroker):
    """Run tasks synchronously, in-process, on enqueue (tests / minimal dev).

    ``.send()`` executes the actor immediately and any exception propagates to
    the caller — there is no worker loop, so no retries or dead-lettering. Keeps
    the test suite free of Redis and a running worker.
    """

    def enqueue(self, message, *, delay=None):
        actor = self.get_actor(message.actor_name)
        actor.fn(*message.args, **message.kwargs)
        return message


def _no_retry_by_default(instance):
    """dramatiq retries a failure 20 times by default, where Celery never
    retried on its own: a task opts in with its own ``max_retries``."""
    for middleware in instance.middleware:
        if isinstance(middleware, Retries):
            middleware.max_retries = 0


def _make_broker():
    # Lazy imports so the eager path never pulls in redis/streams.
    # pylint: disable=import-outside-toplevel
    if getattr(settings, "WORKER_EAGER", False):
        from dramatiq.results.backends import StubBackend

        instance = EagerBroker()
        instance.add_middleware(Results(backend=StubBackend()))
        _no_retry_by_default(instance)
        return instance

    # pylint: disable-next=no-name-in-module
    from dramatiq.results.backends import RedisBackend
    from dramatiq_redis_streams import StreamsBroker

    instance = StreamsBroker(
        url=settings.WORKER_BROKER_URL,
        namespace=settings.WORKER_QUEUE_NAMESPACE,
    )
    # Only the healthcheck's ping stores a result (see transfers/health.py).
    instance.add_middleware(
        Results(
            backend=RedisBackend(
                url=settings.WORKER_BROKER_URL,
                namespace=settings.WORKER_QUEUE_NAMESPACE,
            )
        )
    )
    if settings.SENTRY_DSN:
        # after_* hooks run in reverse order: this one sees Retries' verdict.
        instance.add_middleware(_SentryMiddleware(), before=Retries)
    _no_retry_by_default(instance)
    return instance


# Built once, at import. Every module declaring actors imports this one first,
# so they bind to this broker; ``worker.py`` hands the task CLI
# ``transfers.broker:broker``.
broker = _make_broker()
dramatiq.set_broker(broker)
