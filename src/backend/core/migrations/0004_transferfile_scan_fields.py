from django.db import migrations, models


def grandfather_existing_files_clean(apps, schema_editor):
    """Existing files predate antivirus scanning — mark them CLEAN so they
    stay downloadable. Only files uploaded after this migration go through
    the PENDING → CLEAN gate."""
    TransferFile = apps.get_model("core", "TransferFile")
    TransferFile.objects.all().update(scan_status="clean")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_transfer_auto_archive_on_download_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="transferfile",
            name="scan_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("clean", "Clean"),
                    ("infected", "Infected"),
                    ("error", "Error"),
                ],
                default="pending",
                help_text="Antivirus scan state. A file is only downloadable "
                "once it is CLEAN; the download path fails closed on anything "
                "else. Driven by the clamav file-scanner service's webhook "
                "callback.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="transferfile",
            name="scan_job_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Job id returned by the file-scanner service when "
                "the scan was submitted. Kept for traceability / debugging.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="transferfile",
            name="webhook_secret",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Per-file opaque token embedded in the scan callback "
                "URL. The scanner echoes it back; the webhook compares it "
                "(constant-time) before trusting the result. Generated when "
                "the scan is submitted.",
                max_length=64,
            ),
        ),
        migrations.RunPython(
            grandfather_existing_files_clean, reverse_code=noop_reverse
        ),
    ]
