"""Rename the closure vocabulary from ``revoke*`` to ``deactivate*``.

Column rename (``revoked_at → deactivated_at``) preserves data via
``RenameField``. Status and event-type values are rewritten in-place via
a data migration, then the choice lists are narrowed to only the new
values.

Pure rename: no behavioural change. The deactivate flow still does a
synchronous S3 wipe + status flip, same as the old ``revoke``.
"""

from django.db import migrations, models


def rename_enum_values(apps, schema_editor):
    Transfer = apps.get_model("core", "Transfer")
    TransferEvent = apps.get_model("core", "TransferEvent")
    Transfer.objects.filter(status="revoked").update(status="deactivated")
    TransferEvent.objects.filter(event_type="transfer_revoked").update(
        event_type="transfer_deactivated"
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_remove_transfer_sensitive"),
    ]

    operations = [
        # --- column rename preserves the data in place. ---
        migrations.RenameField(
            model_name="transfer",
            old_name="revoked_at",
            new_name="deactivated_at",
        ),
        # --- widen choices to allow both old and new values during the
        # data rewrite (Django doesn't enforce choices at the DB level,
        # but we also want the ``max_length`` bump applied now). ---
        migrations.AlterField(
            model_name="transfer",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("expired", "Expired"),
                    ("revoked", "Revoked"),
                    ("deactivated", "Deactivated"),
                ],
                default="active",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="transferevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("transfer_created", "Transfer Created"),
                    ("email_sent", "Email Sent"),
                    ("link_opened", "Link Opened"),
                    ("file_downloaded", "File Downloaded"),
                    ("transfer_revoked", "Transfer Revoked"),
                    ("transfer_deactivated", "Transfer Deactivated"),
                    ("transfer_expired", "Transfer Expired"),
                    ("files_deleted", "Files Deleted"),
                ],
                max_length=30,
            ),
        ),
        migrations.RunPython(rename_enum_values, reverse_code=noop),
        # --- narrow choices back to only the new values. ---
        migrations.AlterField(
            model_name="transfer",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("expired", "Expired"),
                    ("deactivated", "Deactivated"),
                ],
                default="active",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="transferevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("transfer_created", "Transfer Created"),
                    ("email_sent", "Email Sent"),
                    ("link_opened", "Link Opened"),
                    ("file_downloaded", "File Downloaded"),
                    ("transfer_deactivated", "Transfer Deactivated"),
                    ("transfer_expired", "Transfer Expired"),
                    ("files_deleted", "Files Deleted"),
                ],
                max_length=30,
            ),
        ),
    ]
