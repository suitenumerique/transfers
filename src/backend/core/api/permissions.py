"""Permission handlers for the transferts core app."""

from rest_framework import permissions


class IsAuthenticated(permissions.BasePermission):
    """Allows access only to authenticated users."""

    def has_permission(self, request, view):
        return bool(request.auth) or request.user.is_authenticated
