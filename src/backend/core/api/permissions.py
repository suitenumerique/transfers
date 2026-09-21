"""Permission handlers for the transferts core app."""

import logging

from rest_framework import permissions, status
from rest_framework.exceptions import APIException, PermissionDenied

from core.entitlements import EntitlementsUnavailableError, get_entitlements_backend

logger = logging.getLogger(__name__)


class EntitlementsUnavailable(APIException):
    """503 raised when the entitlements service cannot be reached to decide."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Access could not be verified. Please try again shortly."
    default_code = "entitlements_unavailable"


class IsAuthenticated(permissions.BasePermission):
    """Allows access only to authenticated users."""

    def has_permission(self, request, view):
        return bool(request.auth) or request.user.is_authenticated


def enforce_upload_entitlement(user):
    """Gate a draft upload action on ``can_access`` from the entitlements backend.

    Mirrors the login check so a mid-session revocation stops uploads within
    the cache window. A reachable-but-denying backend yields 403 (carrying the
    ``reason``); an unreachable one yields 503 so the client can retry rather
    than read the outage as a permanent denial.
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    try:
        payload = get_entitlements_backend().can_access(user)
    except EntitlementsUnavailableError as exc:
        logger.warning("Entitlements service unavailable for the upload gate")
        raise EntitlementsUnavailable() from exc
    if payload.get("result") is True:
        return
    logger.info("Upload denied by entitlements")
    detail = {"detail": "You do not have permission to upload files."}
    reason = payload.get("reason")
    if reason:
        detail["reason"] = reason
    raise PermissionDenied(detail=detail)


class DraftUploadEntitlementPermission(permissions.BasePermission):
    """Require ``can_access`` before draft actions that perform multipart upload work."""

    _UPLOAD_ACTIONS = frozenset(
        {"add_file", "sign_part", "complete_upload", "finalize"}
    )

    def has_permission(self, request, view):
        if getattr(view, "action", None) not in self._UPLOAD_ACTIONS:
            return True
        enforce_upload_entitlement(request.user)
        return True
