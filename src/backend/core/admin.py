"""Admin classes and registrations for core app."""

from django.contrib import admin
from django.contrib.auth import admin as auth_admin

from . import models


@admin.register(models.User)
class UserAdmin(auth_admin.UserAdmin):
    """Admin for User model."""

    list_display = ("email", "full_name", "is_active", "is_staff")
    search_fields = ("email", "full_name", "sub")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("sub", "email", "full_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"fields": ("admin_email", "password1", "password2")}),)


class TransferFileInline(admin.TabularInline):
    """Inline of finalized files on a Transfer. Draft-owned files are shown
    on ``TransferDraftAdmin`` instead — the two parents are mutually
    exclusive at the DB level."""

    model = models.TransferFile
    fk_name = "transfer"
    extra = 0
    readonly_fields = ("filename", "size", "mime_type", "s3_key", "created_at")
    can_delete = False


class TransferDraftFileInline(admin.TabularInline):
    """Inline of files on a TransferDraft."""

    model = models.TransferFile
    fk_name = "draft"
    extra = 0
    readonly_fields = ("filename", "size", "mime_type", "s3_key", "created_at")
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
    list_filter = ("status",)
    search_fields = ("id", "title", "public_token", "owner__email")
    readonly_fields = (
        "id",
        "public_token",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"
    inlines = [TransferFileInline]


@admin.register(models.TransferDraft)
class TransferDraftAdmin(admin.ModelAdmin):
    """Admin for TransferDraft — ephemeral upload sessions.

    Drafts never carry metadata; the listing just shows ownership and age
    so an operator can eyeball which uploads are stuck.
    """

    list_display = ("id", "owner", "created_at")
    search_fields = ("id", "owner__email")
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [TransferDraftFileInline]


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
    readonly_fields = ("id", "created_at", "updated_at")

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
