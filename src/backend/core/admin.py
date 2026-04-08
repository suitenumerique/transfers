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
    add_fieldsets = (
        (None, {"fields": ("admin_email", "password1", "password2")}),
    )
