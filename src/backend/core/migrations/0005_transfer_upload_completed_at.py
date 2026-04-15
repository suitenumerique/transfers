from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_transfer_password_hash"),
    ]

    operations = [
        migrations.AddField(
            model_name="transfer",
            name="upload_completed_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Set once all TransferFile uploads have been completed and "
                    "the transfer has been finalized. Until then, the transfer "
                    "is not listed, not downloadable, and has no public token."
                ),
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="transfer",
            name="public_token",
            field=models.CharField(
                blank=True,
                db_index=True,
                default=None,
                help_text=(
                    "Set once the transfer is finalized (all files uploaded). "
                    "Until then, the transfer has no public link."
                ),
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
    ]
