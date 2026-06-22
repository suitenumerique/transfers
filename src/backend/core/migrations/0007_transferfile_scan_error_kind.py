from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_alter_user_sub"),
        ("core", "0006_alter_transferfile_scan_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="transferfile",
            name="scan_error_kind",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Set only when scan_status is ERROR. 'transient' = an "
                    "infrastructure failure that a retry may clear; 'file' = "
                    "the file itself can't be scanned, so the user must remove "
                    "it."
                ),
                max_length=10,
            ),
        ),
    ]
