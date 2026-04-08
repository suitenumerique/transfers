#!/usr/bin/env python
"""Background task worker for Transferts."""

import argparse
import logging
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "transferts.settings")
os.environ.setdefault("DJANGO_CONFIGURATION", "Development")

# Override $APP if set by the host (e.g. Scalingo)
os.environ.pop("APP", None)

from configurations.importer import install  # pylint: disable=wrong-import-position

install(check_options=True)

from transferts.celery_app import app  # pylint: disable=wrong-import-position

ALL_QUEUES = ["default"]
DEFAULT_QUEUES = ALL_QUEUES


def parse_args():
    parser = argparse.ArgumentParser(description="Start the Transferts worker.")
    parser.add_argument("--queues", "-Q", type=str, default=None)
    parser.add_argument("--concurrency", "-c", type=int, default=None)
    parser.add_argument("--disable-scheduler", action="store_true")
    parser.add_argument("--loglevel", "-l", type=str, default="INFO")
    return parser.parse_args()


def main():
    logger = logging.getLogger(__name__)
    args = parse_args()

    queues = [q.strip() for q in args.queues.split(",")] if args.queues else DEFAULT_QUEUES.copy()

    worker_args = [
        "worker",
        f"--queues={','.join(queues)}",
        f"--loglevel={args.loglevel}",
    ]

    if args.concurrency:
        worker_args.append(f"--concurrency={args.concurrency}")

    if not args.disable_scheduler:
        worker_args.append("--beat")

    worker_args.append("--task-events")

    logger.info("Starting worker with queues: %s", ", ".join(queues))
    app.worker_main(argv=worker_args)


if __name__ == "__main__":
    main()
