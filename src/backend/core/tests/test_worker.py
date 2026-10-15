"""Tests for the task-queue wiring: broker, actors, schedule, worker CLI,
healthcheck and the admin-mounted worker dashboard."""

from argparse import Namespace

from django.conf import settings
from django.test import Client

import dramatiq
import pytest
from dramatiq.middleware import Retries
from dramatiq_crontab import scheduler as cron_registry

from core import tasks
from core.factories import UserFactory

from transfers import health
from transfers.broker import EagerBroker

pytestmark = pytest.mark.django_db

# Every actor the worker must know about: a missing import would leave an
# enqueued task silently unconsumed.
EXPECTED_ACTORS = {
    "deactivate_expired_transfers_task",
    "sweep_orphan_s3_storage_task",
    "cleanup_abandoned_drafts_task",
    "import_drive_file_task",
    "submit_scan_task",
    "reap_stale_pending_scans_task",
    "delete_pending_transfer_files_task",
    "send_recipient_invitations_task",
    "send_download_receipt_task",
    "ping",
}

# The periodic ones, at the frequency Celery beat ran them.
EXPECTED_CRON_JOBS = {
    "deactivate_expired_transfers_task",
    "delete_pending_transfer_files_task",
    "reap_stale_pending_scans_task",
    "cleanup_abandoned_drafts_task",
    "sweep_orphan_s3_storage_task",
}


def test_eager_broker_in_tests():
    """The Test config runs tasks synchronously: no Redis, no worker."""
    assert settings.WORKER_EAGER is True
    assert isinstance(dramatiq.get_broker(), EagerBroker)


def test_all_task_actors_registered():
    """Every task actor is registered on the broker."""
    missing = EXPECTED_ACTORS - set(dramatiq.get_broker().actors)
    assert not missing, f"actors not registered on the broker: {missing}"


def test_cron_jobs_registered():
    """The periodic tasks land on the scheduler the worker sidecar drives."""
    scheduled = {job.name for job in cron_registry.get_jobs()}
    missing = EXPECTED_CRON_JOBS - scheduled
    assert not missing, f"cron jobs not scheduled: {missing}"


def test_send_runs_synchronously_under_eager_broker():
    """task.send(...) enqueues; the eager broker runs it in-process."""
    calls = []

    @dramatiq.actor
    def _probe(value):
        calls.append(value)

    assert _probe.send(42) is not None
    assert calls == [42]


def test_tasks_do_not_retry_unless_they_ask():
    """dramatiq retries 20 times by default; Celery never retried on its own."""
    retries = next(
        m for m in dramatiq.get_broker().middleware if isinstance(m, Retries)
    )
    assert retries.max_retries == 0
    assert "max_retries" not in tasks.send_recipient_invitations_task.options
    assert tasks.submit_scan_task.options["max_retries"] == 3
    assert tasks.send_download_receipt_task.options["max_retries"] == 3


def test_ping_answers_pong():
    """The healthcheck actor answers."""
    assert health.ping.fn() == "pong"


class TestWorkerArgv:
    """worker.py builds the dramatiq CLI argv."""

    @staticmethod
    def _args(**over):
        base = {
            "queues": None,
            "processes": None,
            "threads": None,
            "scheduler": True,
            "verbose": False,
        }
        base.update(over)
        return Namespace(**base)

    def test_scheduler_forked_by_default(self):
        """The embedded scheduler ships as a --fork-function unless opted out."""
        import worker  # pylint: disable=import-outside-toplevel

        argv = worker.build_argv(self._args(), ["default"])
        assert argv[argv.index("--fork-function") + 1] == worker.SCHEDULER

    def test_no_scheduler_flag_omits_sidecar(self):
        """--no-scheduler drops the sidecar."""
        import worker  # pylint: disable=import-outside-toplevel

        argv = worker.build_argv(self._args(scheduler=False), ["default"])
        assert "--fork-function" not in argv

    def test_broker_first_and_queues_last(self):
        """--path is not passed (its nargs='*' would eat the positionals), and
        the container's ping queue is always consumed."""
        import worker  # pylint: disable=import-outside-toplevel

        argv = worker.build_argv(self._args(), ["default"])
        assert argv[:4] == ["dramatiq", worker.BROKER, *worker.TASK_MODULES]
        assert argv[-3:] == ["--queues", "default", health.PING_QUEUE]
        assert "--path" not in argv


class TestDashboardAuth:
    """The dashboard has destructive endpoints and no authentication of its
    own: only superusers reach it, and its POSTs must come from this site."""

    URL = f"/{settings.ADMIN_URL}/worker-dashboard/"

    @staticmethod
    def _client(**user):
        # Enforce CSRF like a browser would meet it: the test client skips it.
        client = Client(enforce_csrf_checks=True)
        client.force_login(UserFactory(is_active=True, **user))
        return client

    def test_anonymous_is_redirected_to_admin_login(self):
        """An unauthenticated visitor is sent to the admin login."""
        resp = Client().get(self.URL)
        assert resp.status_code == 302
        assert f"/{settings.ADMIN_URL}/login/" in resp["Location"]

    def test_non_staff_is_redirected(self):
        """A signed-in agent who is not staff cannot reach it."""
        assert self._client(is_staff=False).get(self.URL).status_code == 302

    def test_staff_without_superuser_is_refused(self):
        """Staff alone is not enough for destructive queue control."""
        assert self._client(is_staff=True).get(self.URL).status_code == 403

    def test_superuser_sees_dashboard(self):
        """The index renders without touching Redis."""
        resp = self._client(is_staff=True, is_superuser=True).get(self.URL)
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/html")

    def test_cross_site_post_is_refused(self):
        """A POST from another origin, or with none, never reaches the app."""
        client = self._client(is_staff=True, is_superuser=True)
        url = f"{self.URL}api/queues/default/flush"
        for origin in ("https://evil.example", None):
            headers = {"HTTP_ORIGIN": origin} if origin else {}
            assert client.post(url, **headers).status_code == 403

    def test_same_origin_post_reaches_the_app(self):
        """The dashboard's own fetch() calls get through the guard."""
        client = self._client(is_staff=True, is_superuser=True)
        resp = client.post(
            f"{self.URL}api/does-not-exist", HTTP_ORIGIN="http://testserver"
        )
        assert resp.status_code == 404
