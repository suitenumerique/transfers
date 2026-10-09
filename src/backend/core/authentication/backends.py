"""Authentication Backends for the transfers core app."""

import logging

from django.conf import settings
from django.contrib import auth
from django.core.exceptions import SuspiciousOperation

from lasuite.oidc_login.backends import (
    OIDCAuthenticationBackend as LaSuiteOIDCAuthenticationBackend,
)

from core.authentication import (
    LOGIN_ERROR_ACCESS_DENIED,
    LOGIN_ERROR_UNAVAILABLE,
    OIDC_ACCESS_DENIED_SESSION_KEY,
    UserCannotAccessApp,
)
from core.entitlements import EntitlementsUnavailableError, get_entitlements_backend
from core.models import DuplicateEmailError, User

logger = logging.getLogger(__name__)


class OIDCAuthenticationBackend(LaSuiteOIDCAuthenticationBackend):
    """Custom OIDC Authentication Backend.

    Handles user creation/update from OIDC claims (ProConnect).
    """

    def authenticate(self, request, **kwargs):
        """Authenticate via OIDC and map entitlement outcomes to login failure.

        A denial and an unreachable entitlements service both fail the login,
        but carry different reasons so the callback can tell the user which
        happened (offer excludes the service vs. try again shortly).
        """
        try:
            return super().authenticate(request, **kwargs)
        except UserCannotAccessApp:
            logger.info("User denied app access by entitlements")
            # The callback only logs out on ``?error=``: a denied re-login
            # would otherwise leave the previous session signed in.
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                auth.logout(request)
            return self._fail_login(request, LOGIN_ERROR_ACCESS_DENIED)
        except EntitlementsUnavailableError:
            logger.warning("Entitlements service unavailable during login")
            return self._fail_login(request, LOGIN_ERROR_UNAVAILABLE)

    @staticmethod
    def _fail_login(request, reason):
        """Record why the login failed and signal failure (None) to the OIDC flow."""
        request.session[OIDC_ACCESS_DENIED_SESSION_KEY] = reason
        request.session.modified = True

    def get_or_create_user(self, access_token, id_token, payload):
        """Resolve the user from userinfo, then gate on app entitlements.

        Identity handling (match, create, disabled-account and claims checks)
        stays in the base backend; this override only adds the entitlements
        gate. When the base declines (no match and ``OIDC_CREATE_USER`` off) it
        returns ``None`` and the login fails cleanly, without ever running the
        gate on a null user.
        """
        user = super().get_or_create_user(access_token, id_token, payload)
        if user is None:
            return None

        result = get_entitlements_backend().can_access(user)
        if not result["result"]:
            raise UserCannotAccessApp(
                result.get("reason") or "User does not have access to the app"
            )
        return user

    def get_extra_claims(self, user_info):
        """Get extra claims from user info."""
        claims_to_store = {
            claim: value
            for claim in getattr(settings, "OIDC_STORE_CLAIMS", [])
            if (value := user_info.get(claim)) is not None
        }
        return {
            "full_name": self.compute_full_name(user_info),
            "claims": claims_to_store,
        }

    def update_user_if_needed(self, user, claims):
        """Update the user, persisting ``claims`` outside the base method.

        The base logs old and new values (siret included) and skips falsy ones,
        so a claim the IdP stopped sending would stay on ``User.claims``.
        """
        claims = dict(claims)
        stored_claims = claims.pop("claims", None)
        super().update_user_if_needed(user, claims)
        if stored_claims is not None and stored_claims != user.claims:
            logger.info("Update 'claims' field")
            user.claims = stored_claims
            user.save(update_fields=("claims",))

    def get_existing_user(self, sub, email):
        """Get an existing user by sub or email."""
        try:
            return User.objects.get_user_by_sub_or_email(sub, email)
        except DuplicateEmailError as err:
            raise SuspiciousOperation(err.message) from err
