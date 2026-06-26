from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_transferfile_scan_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="transfer",
            name="e2e_encrypted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="transfer",
            name="encryption_chunk_size",
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    "Plaintext bytes per crypto chunk; ciphertext part on S3 "
                    "is this + 28 bytes (12-byte IV + 16-byte GCM tag). Null "
                    "when the transfer is not E2E-encrypted."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="transferdraft",
            name="e2e_encrypted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="transferdraft",
            name="encryption_chunk_size",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transferfile",
            name="plaintext_size",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text=(
                    "Decoded file size before encryption. Null when the "
                    "parent transfer is not E2E-encrypted — UIs should fall "
                    "back to ``size``."
                ),
                null=True,
            ),
        ),
    ]
