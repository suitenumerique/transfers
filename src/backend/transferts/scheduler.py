"""Embedded periodic-task scheduler — runs inside the worker, not its own container.

Each worker process forks exactly one of these as a dramatiq ``--fork-function``
sidecar (wired in ``worker.py``). Every sidecar contends for a single Redis lock,
so at most one is the *active* scheduler at any time; when the leader stops or its
container dies, the lock frees (explicit release, or ``LOCK_TIMEOUT`` TTL expiry)
and a standby takes over. Scale the ``worker`` process to N containers and you get
N standbys with automatic failover and no dedicated scheduler dyno.

The schedule itself is declared by the ``@cron_task`` decorators in
``core/tasks.py``; this module only decides *which* worker fires it.

dramatiq calls this function once and does not restart it, so it must never
return on its own — it loops until the process is signalled.
"""

import logging
import time

from django.utils import timezone

from apscheduler.schedulers.background import BackgroundScheduler
from dramatiq_crontab import scheduler as registry
from dramatiq_crontab import utils
from dramatiq_crontab.conf import get_settings

logger = logging.getLogger(__name__)


def _build_scheduler():
    """A ``BackgroundScheduler`` seeded with the ``@cron_task`` jobs, started paused.

    The jobs were registered on dramatiq_crontab's global (never-started)
    scheduler when ``core.tasks`` was imported; we copy them onto a background
    scheduler that we can pause/resume as leadership changes hands.
    """
    sched = BackgroundScheduler(timezone=timezone.get_default_timezone())
    for job in registry.get_jobs():
        sched.add_job(
            job.func,
            trigger=job.trigger,
            args=job.args,
            kwargs=job.kwargs,
            id=job.id,
            name=job.name,
            replace_existing=True,
        )
    sched.start(paused=True)
    return sched


def run_scheduler():
    """Fork-function entrypoint: contend for leadership and drive the schedule.

    Blocks until the process is signalled (dramatiq's fork handler raises
    ``SystemExit`` on SIGTERM, which unwinds through the ``finally`` blocks and
    releases the lock).
    """
    conf = get_settings()
    refresh = conf.LOCK_REFRESH_INTERVAL  # pylint: disable=no-member
    ttl = conf.LOCK_TIMEOUT  # pylint: disable=no-member
    lock = utils.lock

    sched = _build_scheduler()
    logger.info("Scheduler sidecar ready with %d job(s).", len(sched.get_jobs()))

    # No Redis lock configured (no DRAMATIQ_CRONTAB REDIS_URL): fall back to a
    # single active scheduler with no leader election. In our settings the URL
    # is always set, so this only guards misconfiguration / minimal setups.
    if isinstance(lock, utils.FakeLock):
        logger.warning(
            "No scheduler lock configured — running without leader election. "
            "Do not run more than one worker, or tasks will fire multiple times."
        )
        try:
            sched.resume()
            while True:
                time.sleep(refresh)
        finally:
            sched.shutdown(wait=False)
        return

    try:
        while True:
            # Block up to one refresh interval trying to become leader; loop and
            # retry if another worker already holds it.
            if not lock.acquire(blocking=True, blocking_timeout=refresh):
                continue
            logger.info("Acquired scheduler lock — this worker is now scheduling.")
            try:
                sched.resume()
                # Hold leadership by extending the lock; extend() raises when we
                # no longer own it (e.g. a TTL lapse after a Redis blip).
                while True:
                    time.sleep(refresh)
                    lock.extend(ttl, replace_ttl=True)
            except utils.LockError:
                logger.warning(
                    "Lost the scheduler lock — stepping down and re-contending."
                )
            finally:
                sched.pause()
                try:
                    lock.release()
                except utils.LockError:
                    pass
    finally:
        sched.shutdown(wait=False)
