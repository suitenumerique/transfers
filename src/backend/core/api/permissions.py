"""Permission handlers for the transferts core app."""

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from core.entitlements import get_entitlements_backend


class IsAuthenticated(permissions.BasePermission):
    """Allows access only to authenticated users."""

    def has_permission(self, request, view):
        return bool(request.auth) or request.user.is_authenticated


def enforce_upload_entitlement(user):
    """Raise ``PermissionDenied`` unless the entitlements backend allows upload.

    Centralises the ``can_upload`` check used by draft endpoints that create
    or advance a browser-side multipart upload. Callers should rely on this
    helper (or :class:`DraftUploadEntitlementPermission`) instead of
    duplicating backend lookups.
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    payload = get_entitlements_backend().can_upload(user)
    if payload.get("result") is True:
        return
    detail = {"detail": "You do not have permission to upload files."}
    reason = payload.get("reason")
    if reason:
        detail["reason"] = reason
    raise PermissionDenied(detail=detail)


class DraftUploadEntitlementPermission(permissions.BasePermission):
    """Require ``can_upload`` for draft actions that perform multipart upload work."""

    _UPLOAD_ACTIONS = frozenset({"add_file", "sign_part", "complete_upload"})

    def has_permission(self, request, view):
        if getattr(view, "action", None) not in self._UPLOAD_ACTIONS:
            return True
        enforce_upload_entitlement(request.user)
        return True
