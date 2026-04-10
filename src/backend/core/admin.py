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
    model = models.TransferFile
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
        "files_deleted_at",
        "created_at",
    )
    list_filter = ("status", "sensitive", "files_deleted_at")
    search_fields = ("id", "title", "public_token", "owner__email")
    readonly_fields = (
        "id",
        "public_token",
        "created_at",
        "updated_at",
        "files_deleted_at",
    )
    date_hierarchy = "created_at"
    inlines = [TransferFileInline]


@admin.register(models.TransferFile)
class TransferFileAdmin(admin.ModelAdmin):
    """Admin for TransferFile model."""

    list_display = ("id", "filename", "size", "mime_type", "transfer", "created_at")
    search_fields = ("filename", "transfer__id")
    readonly_fields = ("id", "created_at", "updated_at")


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
