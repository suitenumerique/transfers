# Catches up the migration state with the timezone default. It used to be
# settings.TIME_ZONE read at import, so the state froze whatever the machine
# that ran makemigrations had; a callable serialises as a reference and reads
# the setting per row, so every deployment records the same state.
import timezone_field.fields
from django.db import migrations

import core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_transferfile_scan_report"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="timezone",
            field=timezone_field.fields.TimeZoneField(
                choices_display="WITH_GMT_OFFSET",
                default=core.models.default_timezone,
                help_text="The timezone in which the user wants to see times.",
                use_pytz=False,
            ),
        ),
    ]
