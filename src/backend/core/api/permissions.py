"""Permission handlers for the transfers core app."""

import logging

from rest_framework import permissions, status
from rest_framework.exceptions import APIException, PermissionDenied

from core.entitlements import EntitlementsUnavailableError, get_entitlements_backend
from core.services import deposits

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
        {"add_file", "sign_part", "complete_upload", "finalize", "rescan"}
    )

    def has_permission(self, request, view):
        if getattr(view, "action", None) not in self._UPLOAD_ACTIONS:
            return True
        enforce_upload_entitlement(request.user)
        return True


def deposits_closed_body():
    return {
        "detail": "This recipient no longer accepts deposits.",
        "reason": "closed",
    }


class DepositCapabilityPermission(permissions.BasePermission):
    """The ``X-Deposit-Token`` header carries a depositor's upload session.

    Re-checked on every call: the challenge must be verified and unused,
    its target still open (space not revoked, address still allowed), and
    the space's owner still entitled to the app. Sets
    ``request.deposit_challenge``. Views using it have no authentication
    class, so a refusal is a 403, never the 401 the frontend reads as
    "signed out"."""

    def has_permission(self, request, view):
        challenge = deposits.load_session(request.headers.get("X-Deposit-Token", ""))
        if challenge is None:
            raise PermissionDenied(
                {"detail": "This deposit session is not valid.", "reason": "session"}
            )
        if not deposits.target_open(challenge):
            raise PermissionDenied(deposits_closed_body())
        if challenge.deposit_space_id is not None:
            # Report the space as closed, without the reason the owner lost access.
            try:
                enforce_upload_entitlement(challenge.deposit_space.owner)
            except PermissionDenied as exc:
                raise PermissionDenied(deposits_closed_body()) from exc
        request.deposit_challenge = challenge
        return True
