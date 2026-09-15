# Per-recipient download attribution + opt-in download receipts.

import secrets

from django.db import migrations, models

import core.models


def fill_recipient_tokens(apps, schema_editor):
    """Existing recipients predate the token: mint one per row so the
    column can become NOT NULL + unique. Links already emailed to them
    carry no ``?r=``, so their activity stays unattributed — expected."""
    TransferRecipient = apps.get_model("core", "TransferRecipient")
    for recipient in TransferRecipient.objects.filter(token__isnull=True).iterator():
        recipient.token = secrets.token_urlsafe(24)
        recipient.save(update_fields=["token"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_transfer_confidential_transfer_encryption_chunk_size_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="transfer",
            name="notify_on_download",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="transferrecipient",
            name="download_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transferrecipient",
            name="delayed_receipt_armed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transferrecipient",
            name="token",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.RunPython(fill_recipient_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="transferrecipient",
            name="token",
            field=models.CharField(
                db_index=True,
                default=core.models._generate_recipient_token,
                max_length=64,
                unique=True,
            ),
        ),
    ]
