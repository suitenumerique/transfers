#!/usr/bin/env python
"""Background task worker for Transferts.

Runs a task worker against the custom Redis Streams broker. The periodic
scheduler runs *inside* this process as a forked sidecar (leader-elected via a
Redis lock), so there is no separate scheduler container — scale the ``worker``
process and one instance schedules while the rest stand by. See
``transferts/scheduler.py``.

Usage:
    python worker.py                    # all queues + embedded scheduler
    python worker.py --queues=default   # only specific queues
    python worker.py --processes=4      # number of worker processes
    python worker.py --no-scheduler     # don't run the embedded scheduler
    python worker.py -v                 # verbose (debug logging)
"""

import argparse
import logging
import multiprocessing
import os
import sys

# Dramatiq + Python 3.14: "forkserver" (the new default start method) breaks
# dramatiq's shared-memory Canteen, so workers silently never consume. Force
# "fork" before dramatiq spawns any process.
# See https://github.com/Bogdanp/dramatiq/issues/701
multiprocessing.set_start_method("fork", force=True)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "transferts.settings")
os.environ.setdefault("DJANGO_CONFIGURATION", "Development")

# Override $APP if set by the host (e.g. Scalingo)
os.environ.pop("APP", None)

from configurations.importer import install  # pylint: disable=wrong-import-position

install(check_options=True)

import django  # pylint: disable=wrong-import-position

# Runs CoreConfig.ready(): installs the broker and imports the task modules so
# every actor is registered before the dramatiq CLI takes over.
django.setup()

DEFAULT_QUEUES = ["default"]

# ``module:attr`` — the task CLI imports the module and uses its ``broker``
# attribute (set by transferts.broker.configure()); TASK_MODULES register the actors.
BROKER = "transferts.broker:broker"
TASK_MODULES = ["core.tasks"]
# Leader-elected periodic scheduler, run as a dramatiq fork-function sidecar.
SCHEDULER = "transferts.scheduler:run_scheduler"


def parse_args():
    """Parse the worker's command-line arguments."""
    parser = argparse.ArgumentParser(description="Start the Transferts task worker.")
    parser.add_argument("--queues", "-Q", type=str, default=None)
    parser.add_argument("--processes", "-p", type=int, default=None)
    parser.add_argument("--threads", "-t", type=int, default=None)
    parser.add_argument(
        "--no-scheduler",
        dest="scheduler",
        action="store_false",
        help="Don't run the embedded periodic-task scheduler.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def build_argv(args, queues):
    """Build the argv handed to the dramatiq CLI from parsed args + queues.

    No ``--path`` is passed: dramatiq already defaults it to ``["."]``, and its
    ``nargs="*"`` would otherwise swallow the broker/module positionals.
    """
    argv = ["dramatiq", BROKER, *TASK_MODULES]
    if args.processes:
        argv += ["--processes", str(args.processes)]
    if args.threads:
        argv += ["--threads", str(args.threads)]
    if args.scheduler:
        # dramatiq forks this once and manages its lifecycle alongside the
        # workers; leader election lets every worker run it safely.
        argv += ["--fork-function", SCHEDULER]
    if args.verbose:
        argv += ["-v"]
    # --queues takes a variable number of values, so keep it last.
    argv += ["--queues", *queues]
    return argv


def main():
    """Start the dramatiq worker for the requested queues."""
    logger = logging.getLogger(__name__)
    args = parse_args()

    queues = (
        [q.strip() for q in args.queues.split(",")]
        if args.queues
        else DEFAULT_QUEUES.copy()
    )

    logger.info("Starting dramatiq worker with queues: %s", ", ".join(queues))

    import dramatiq.cli  # pylint: disable=wrong-import-position,import-outside-toplevel

    sys.argv = build_argv(args, queues)
    dramatiq.cli.main()


if __name__ == "__main__":
    main()
