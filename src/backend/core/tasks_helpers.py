"""Queue-agnostic task registration helpers.

Task modules decorate their functions with ``@register_task`` / ``@cron_task``
imported from here, so they never reference the queue implementation directly —
swapping the broker touches only this module and ``transferts.broker``.
"""

import dramatiq
from dramatiq.brokers.stub import StubBroker
from dramatiq_crontab import cron


class _TaskActor(dramatiq.Actor):
    """Actor with a ``.delay()`` alias for ``.send()``.

    Lets call sites enqueue with ``task.delay(args)``; returns the enqueued
    ``Message``.
    """

    def delay(self, *args, **kwargs):
        """Enqueue the task; alias of ``.send()``."""
        return self.send(*args, **kwargs)


class EagerBroker(StubBroker):
    """Run tasks synchronously, in-process, on enqueue (tests / minimal dev).

    ``.delay()`` executes the actor immediately and any exception propagates to
    the caller — there is no worker loop, so no retries or dead-lettering. Keeps
    the test suite free of Redis and a running worker.
    """

    def enqueue(self, message, *, delay=None):
        actor = self.get_actor(message.actor_name)
        actor.fn(*message.args, **message.kwargs)
        return message


def register_task(fn=None, *, queue="default", **options):
    """Register a function as a background task actor.

    Thin wrapper over :func:`dramatiq.actor`. ``queue`` maps to ``queue_name``;
    any other actor option (``max_retries``, ``min_backoff``, ``time_limit``, …)
    is forwarded. Enqueue the task with ``task.delay(args)``.
    """
    options.setdefault("actor_class", _TaskActor)

    def decorator(func):
        return dramatiq.actor(func, queue_name=queue, **options)

    return decorator(fn) if fn is not None else decorator


def cron_task(*args, **kwargs):
    """Register a periodic schedule (crontab syntax) for a task actor.

    Wraps ``dramatiq_crontab.cron`` so task modules don't import it directly.
    Applied *above* ``@register_task`` (the schedule decorates the actor)::

        @cron_task("*/5 * * * *")
        @register_task
        def sweep(): ...

    The schedule fires only in the scheduler sidecar (``transferts/scheduler.py``);
    importing the module elsewhere merely registers it.
    """
    return cron(*args, **kwargs)
