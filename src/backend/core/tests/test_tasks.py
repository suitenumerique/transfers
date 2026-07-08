"""Tests for the task-queue broker wiring and the admin-mounted worker dashboard."""

from argparse import Namespace

from django.conf import settings
from django.test import Client

import dramatiq
import pytest
from dramatiq_crontab import scheduler as cron_registry

from core.factories import UserFactory
from core.tasks_helpers import EagerBroker, register_task

pytestmark = pytest.mark.django_db

# Every @register_task actor the worker must know about. A missing import in
# core/tasks.py would drop one of these and the worker would silently ignore
# the enqueued task.
EXPECTED_ACTORS = {
    "deactivate_expired_transfers_task",
    "sweep_orphan_s3_storage_task",
    "cleanup_abandoned_drafts_task",
    "import_drive_file_task",
    "submit_scan_task",
    "reap_stale_pending_scans_task",
    "delete_pending_transfer_files_task",
    "send_recipient_invitations_task",
}

# The subset carrying an @cron_task schedule — these must land on the scheduler
# that the worker's embedded sidecar drives.
EXPECTED_CRON_JOBS = {
    "deactivate_expired_transfers_task",
    "delete_pending_transfer_files_task",
    "reap_stale_pending_scans_task",
    "cleanup_abandoned_drafts_task",
    "sweep_orphan_s3_storage_task",
}


def test_eager_broker_in_tests():
    """The Test config runs tasks synchronously — no Redis, no worker."""
    assert settings.WORKER_EAGER is True
    assert isinstance(dramatiq.get_broker(), EagerBroker)


def test_all_task_actors_registered():
    """Every task actor is registered — catches a missing import in core.tasks."""
    registered = set(dramatiq.get_broker().actors)
    missing = EXPECTED_ACTORS - registered
    assert not missing, f"actors not registered on the broker: {missing}"


def test_cron_jobs_registered():
    """The periodic tasks land on the scheduler the worker sidecar drives."""
    scheduled = {job.name for job in cron_registry.get_jobs()}
    missing = EXPECTED_CRON_JOBS - scheduled
    assert not missing, f"cron jobs not scheduled: {missing}"


def test_delay_runs_synchronously_under_eager_broker():
    """task.delay(...) enqueues via the broker; eagerly that runs it in-process."""
    calls = []

    @register_task
    def _probe(value):
        calls.append(value)

    message = _probe.delay(42)
    assert calls == [42]
    assert message is not None  # returns the enqueued Message, like .send()


class TestWorkerArgv:
    """worker.py builds the task-runner CLI argv; the scheduler is a sidecar."""

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
        assert "--fork-function" in argv
        assert worker.SCHEDULER in argv

    def test_no_scheduler_flag_omits_sidecar(self):
        """--no-scheduler drops the sidecar."""
        import worker  # pylint: disable=import-outside-toplevel

        argv = worker.build_argv(self._args(scheduler=False), ["default"])
        assert "--fork-function" not in argv

    def test_broker_first_and_queues_last_without_path(self):
        """--path must not be passed (its nargs='*' would eat the positionals)."""
        import worker  # pylint: disable=import-outside-toplevel

        argv = worker.build_argv(self._args(), ["default"])
        assert argv[:3] == ["dramatiq", worker.BROKER, *worker.TASK_MODULES]
        assert argv[-2:] == ["--queues", "default"]
        assert "--path" not in argv


class TestDashboardAuth:
    """The dashboard is destructive + unauthenticated on its own, so it must sit
    behind the admin staff login."""

    URL = f"/{settings.ADMIN_URL}/worker-dashboard/"

    def test_anonymous_is_redirected_to_admin_login(self):
        """An unauthenticated visitor is bounced to the admin login."""
        resp = Client().get(self.URL)
        assert resp.status_code == 302
        assert f"/{settings.ADMIN_URL}/login/" in resp["Location"]

    def test_non_staff_is_redirected(self):
        """A logged-in non-staff user cannot reach the dashboard."""
        client = Client()
        client.force_login(UserFactory(is_active=True, is_staff=False))
        resp = client.get(self.URL)
        assert resp.status_code == 302

    def test_staff_sees_dashboard(self):
        """A staff user gets the dashboard shell (no Redis needed for the index)."""
        client = Client()
        client.force_login(UserFactory(is_active=True, is_staff=True))
        # The index route renders the dashboard shell without touching Redis.
        resp = client.get(self.URL)
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/html")
