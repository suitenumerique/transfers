from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_transferdraft_encryption_key_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="transferfile",
            index=models.Index(
                condition=models.Q(("scan_status", "PENDING")),
                fields=["scan_submitted_at"],
                name="transferfile_pending_scan_idx",
            ),
        ),
    ]
