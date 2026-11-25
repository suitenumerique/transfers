"""Admin classes and registrations for core app."""

from django.contrib import admin
from django.contrib.auth import admin as auth_admin

from . import models

# Adds a link to the task-queue dashboard on the admin home page.
admin.site.index_template = "admin/worker_dashboard_index.html"


@admin.register(models.User)
class UserAdmin(auth_admin.UserAdmin):
    """Admin for User model."""

    list_display = ("email", "full_name", "is_active", "is_staff")
    search_fields = ("email", "full_name", "sub")
    ordering = ("email",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "sub",
                    "email",
                    "full_name",
                    "claims",
                )
            },
        ),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"fields": ("admin_email", "password1", "password2")}),)
    # Logins match on sub: editing it signs in as that person. Only the IdP
    # sets sub and claims.
    readonly_fields = ("sub", "claims")


# File rows inlined on a transfer or draft, all read-only.
_FILE_FIELDS = (
    "filename",
    "size",
    "plaintext_size",
    "mime_type",
    "s3_key",
    "scan_status",
    "scan_error_kind",
    "created_at",
)


class TransferFileInline(admin.TabularInline):
    """Inline of finalized files on a Transfer. Draft-owned files are shown
    on ``TransferDraftAdmin`` instead — the two parents are mutually
    exclusive at the DB level."""

    model = models.TransferFile
    fk_name = "transfer"
    extra = 0
    fields = _FILE_FIELDS
    readonly_fields = _FILE_FIELDS
    can_delete = False


class TransferDraftFileInline(admin.TabularInline):
    """Inline of files on a TransferDraft."""

    model = models.TransferFile
    fk_name = "draft"
    extra = 0
    fields = _FILE_FIELDS
    readonly_fields = _FILE_FIELDS
    can_delete = False


@admin.register(models.Transfer)
class TransferAdmin(admin.ModelAdmin):
    """Admin for Transfer model."""

    list_display = (
        "id",
        "title",
        "owner",
        "status",
        "expires_at",
        "created_at",
    )
    list_filter = ("status", "direction")
    search_fields = ("id", "title", "public_token", "owner__email", "inbox_email")
    readonly_fields = (
        "id",
        "owner",
        "direction",
        "deposit_space",
        "inbox_email",
        "depositor_name",
        "depositor_email",
        "depositor_verified",
        "public_token",
        "encryption_key",
        "confidential",
        "encryption_chunk_size",
        # Public access hangs on the status: reopening a deactivated transfer
        # here would leave no event in its history.
        "status",
        "deactivation_reason",
        "deactivated_at",
        "pending_deletion_at",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"
    inlines = [TransferFileInline]

    # A transfer comes from a finalize, which this form would bypass.
    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        # Only what the form changed: a full save would write back a status
        # that a task or the owner changed since the form was loaded.
        if change:
            obj.save(update_fields=[*form.changed_data, "updated_at"])
        else:
            obj.save()


@admin.register(models.TransferDraft)
class TransferDraftAdmin(admin.ModelAdmin):
    """Admin for TransferDraft — ephemeral upload sessions.

    Drafts never carry metadata; the listing just shows ownership and age
    so an operator can eyeball which uploads are stuck.
    """

    list_display = ("id", "owner", "deposit_challenge", "created_at")
    search_fields = ("id", "owner__email")
    readonly_fields = (
        "id",
        "owner",
        "deposit_challenge",
        "encryption_key",
        "encryption_chunk_size",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"
    inlines = [TransferDraftFileInline]


class DepositSpaceMemberInline(admin.TabularInline):
    model = models.DepositSpaceMember
    extra = 0
    fields = ("email", "created_at")
    readonly_fields = ("email", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.DepositSpace)
class DepositSpaceAdmin(admin.ModelAdmin):
    """Admin for deposit spaces. ``max_deposit_size`` is only settable here."""

    list_display = ("name", "owner", "retention_days", "expires_at", "created_at")
    list_filter = ("single_use", "verify_email", "confidential")
    search_fields = ("id", "name", "owner__email")
    fields = (
        "id",
        "owner",
        "name",
        "retention_days",
        "max_deposit_size",
        "expires_at",
        "single_use",
        "used_at",
        "verify_email",
        "confidential",
        "created_at",
        "updated_at",
    )
    # The link token is a capability: it never shows here. The owner picks
    # retention_days among DEPOSIT_SPACE_RETENTION_CHOICES.
    readonly_fields = (
        "id",
        "owner",
        "retention_days",
        "expires_at",
        "single_use",
        "used_at",
        "verify_email",
        "confidential",
        "created_at",
        "updated_at",
    )
    inlines = [DepositSpaceMemberInline]

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        # Only what the form changed: a full save would write back a used_at
        # that a deposit set since the form was loaded.
        if change:
            obj.save(update_fields=[*form.changed_data, "updated_at"])
        else:
            obj.save()

    # The API deletes a space's deposit files first; a delete from here
    # would leave them to the orphan sweep.
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.DepositChallenge)
class DepositChallengeAdmin(admin.ModelAdmin):
    """Admin for depositor challenges, read-only."""

    list_display = (
        "id",
        "depositor_email",
        "deposit_space",
        "inbox_email",
        "verified_at",
        "email_verified",
        "consumed_at",
        "created_at",
    )
    search_fields = ("id", "depositor_email", "inbox_email")
    exclude = ("code_hash",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # Deleting one would cascade to its draft and leave the draft's S3
    # objects to the orphan sweep. The daily purge removes challenges.
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.TransferFile)
class TransferFileAdmin(admin.ModelAdmin):
    """Admin for TransferFile — a file that belongs to a Transfer (finalized)
    or a TransferDraft (upload in progress), exactly one of the two.
    """

    list_display = (
        "id",
        "filename",
        "size",
        "mime_type",
        "parent",
        "created_at",
    )
    list_filter = ("mime_type",)
    search_fields = ("filename", "transfer__id", "draft__id")
    # The verdict and its report only come from the scanner; the webhook
    # secret would let anyone holding it forge one.
    exclude = ("webhook_secret",)
    readonly_fields = (
        "id",
        "transfer",
        "draft",
        "s3_key",
        "upload_id",
        "source_url",
        "scan_status",
        "scan_error_kind",
        "scan_submitted_at",
        "scan_job_id",
        "scan_report",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Parent")
    def parent(self, obj):
        if obj.transfer_id:
            return f"Transfer {obj.transfer_id}"
        if obj.draft_id:
            return f"Draft {obj.draft_id}"
        return "-"


@admin.register(models.TransferEvent)
class TransferEventAdmin(admin.ModelAdmin):
    """Admin for TransferEvent model."""

    list_display = (
        "id",
        "transfer_id",
        "event_type",
        "actor_type",
        "actor_id",
        "ip",
        "created_at",
    )
    list_filter = ("event_type", "actor_type")
    search_fields = ("transfer_id", "actor_id", "ip")
    readonly_fields = (
        "id",
        "transfer_id",
        "recipient_id",
        "event_type",
        "actor_type",
        "actor_id",
        "ip",
        "user_agent",
        "payload",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
