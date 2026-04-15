"""Permission handlers for the transferts core app."""

from rest_framework import permissions


class IsAuthenticated(permissions.BasePermission):
    """Allows access only to authenticated users."""

    def has_permission(self, request, view):
        return bool(request.auth) or request.user.is_authenticated


class IsSelf(IsAuthenticated):
    """Allows access only to the user themselves."""

    def has_object_permission(self, request, view, obj):
        return obj == request.user


class IsAuthenticatedOrSafe(IsAuthenticated):
    """Allows access to authenticated users, or anonymous on safe methods."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return super().has_permission(request, view)
