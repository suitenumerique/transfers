"""Worker healthcheck: the dramatiq counterpart of ``celery inspect ping``.

Each worker consumes a queue of its own container, ``ping.<hostname>``, so a
ping is answered by this worker and not another one. ``python worker.py
--ping`` sends one and waits for the answer: that covers the broker, the
consumer, a worker thread and the result backend.
"""

import socket

from django.conf import settings

import dramatiq
from dramatiq.middleware import Middleware
from dramatiq_redis_streams.keys import queues_key, stream_key

from transfers.broker import broker

PING_QUEUE = f"ping.{socket.gethostname()}"


@dramatiq.actor(
    queue_name=PING_QUEUE,
    # Ahead of every task (priority 0) when a worker thread frees.
    priority=-1,
    store_results=True,
    max_retries=0,
    max_age=10_000,  # ms: the prober has given up by then
    result_ttl=30_000,  # ms
)
def ping():
    """Answer the healthcheck."""
    return "pong"


def is_alive(timeout_ms=5_000):
    """Send a ping to this container's worker and wait for its answer."""
    try:
        result = ping.send().get_result(block=True, timeout=timeout_ms)
    # pylint: disable-next=broad-exception-caught
    except Exception:  # any failure means unhealthy
        return False
    # A ping skipped as too old stores None.
    return result == "pong"


class _DropPingQueue(Middleware):
    """Delete this container's ping stream when its worker stops, so a new
    stream per container does not pile up in Redis and on the dashboard. A
    crashed container leaves its stream behind; the dashboard removes it."""

    def after_worker_shutdown(self, broker, worker):  # pylint: disable=redefined-outer-name
        namespace = settings.WORKER_QUEUE_NAMESPACE
        try:
            broker.client.srem(queues_key(namespace), PING_QUEUE)
            broker.client.delete(stream_key(PING_QUEUE, namespace))
        # pylint: disable-next=broad-exception-caught
        except Exception:  # noqa: S110 -- best effort, the worker is exiting
            pass


# The eager broker has no Redis client and no stream to drop.
if hasattr(broker, "client"):
    broker.add_middleware(_DropPingQueue())
