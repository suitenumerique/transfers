from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_transferfile_unscannable_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="transferfile",
            name="scan_report",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "What the scanner answered, as it answered it: the "
                    "per-category verdicts and each engine's own result. "
                    "scan_status is the decision taken from it; this is why. "
                    "Replaced on a rescan."
                ),
            ),
        ),
    ]
