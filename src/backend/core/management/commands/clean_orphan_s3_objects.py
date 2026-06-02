"""Thin CLI over ``core.services.s3_sweep.run_orphan_sweep``.

Two passes (objects + multipart uploads), dry-run by default. The actual
sweep policy lives in the service module so the daily Celery task uses
the same code path.
"""

from django.core.management.base import BaseCommand

from core.services.s3_sweep import run_orphan_sweep


class Command(BaseCommand):
    help = (
        "Delete objects in the transfers bucket whose key is not referenced "
        "by any TransferFile row, and abort orphan multipart uploads. "
        "Dry-run by default — pass --apply to delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete orphan objects (default: dry-run).",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Restrict scan to objects under this S3 prefix (e.g. 'transfers/').",
        )
        parser.add_argument(
            "--min-age",
            type=int,
            default=24,
            help=(
                "Skip objects/MPUs younger than N hours (default 24, sized "
                "to clear in-flight uploads). Pass 0 to ignore age."
            ),
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        result = run_orphan_sweep(
            apply=apply,
            min_age_hours=options["min_age"],
            prefix=options["prefix"],
            write=self.stdout.write,
            write_error=lambda msg: self.stderr.write(self.style.ERROR(msg)),
        )

        verb = "Deleted" if apply else "Would delete"
        verb_mpu = "Aborted" if apply else "Would abort"
        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {result['objects_scanned']} objects. "
                f"{verb} {result['objects_deleted']} orphan(s)."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {result['mpus_scanned']} multipart uploads. "
                f"{verb_mpu} {result['mpus_aborted']} orphan MPU(s)."
            )
        )
        if not apply:
            self.stdout.write("Dry-run only. Re-run with --apply to delete.")
