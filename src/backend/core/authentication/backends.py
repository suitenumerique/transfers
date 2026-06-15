"""Authentication Backends for the transferts core app."""

import logging

from django.conf import settings
from django.core.exceptions import SuspiciousOperation

from lasuite.oidc_login.backends import (
    OIDCAuthenticationBackend as LaSuiteOIDCAuthenticationBackend,
)

from core.authentication import OIDC_ACCESS_DENIED_SESSION_KEY, UserCannotAccessApp
from core.entitlements import get_entitlements_backend
from core.models import DuplicateEmailError, User

logger = logging.getLogger(__name__)


class OIDCAuthenticationBackend(LaSuiteOIDCAuthenticationBackend):
    """Custom OIDC Authentication Backend.

    Handles user creation/update from OIDC claims (ProConnect).
    """

    def authenticate(self, request, **kwargs):
        """Authenticate via OIDC and map entitlement denials to login failure."""
        try:
            return super().authenticate(request, **kwargs)
        except UserCannotAccessApp as exc:
            logger.info("User denied app access: %s", exc)
            request.session[OIDC_ACCESS_DENIED_SESSION_KEY] = True
            request.session.modified = True
            return None

    def get_or_create_user(self, access_token, id_token, payload):
        """Return a User based on userinfo. Create a new user if no match is found."""
        _user_created = False
        user_info = self.get_userinfo(access_token, id_token, payload)

        if not self.verify_claims(user_info):
            raise SuspiciousOperation("Claims verification failed")

        sub = user_info["sub"]
        if not sub:
            raise SuspiciousOperation(
                "User info contained no recognizable user identification"
            )

        email = user_info.get("email")

        claims = {
            self.OIDC_USER_SUB_FIELD: sub,
            "email": email,
        }
        claims.update(**self.get_extra_claims(user_info))

        user = self.get_existing_user(sub, email)

        if user:
            if not user.is_active:
                raise SuspiciousOperation("User account is disabled")
            self.update_user_if_needed(user, claims)
        elif self.get_settings("OIDC_CREATE_USER", True):
            user = self.create_user(claims)
            _user_created = True
        else:
            raise SuspiciousOperation(
                "User not found and OIDC user creation is disabled."
            )

        entitlement_backend = get_entitlements_backend()
        result = entitlement_backend.can_access(user)
        if not result["result"]:
            raise UserCannotAccessApp(
                result.get("message", "User does not have access to the app")
            )
        return user

    def get_extra_claims(self, user_info):
        """Get extra claims from user info."""
        claims_to_store = {
            claim: user_info.get(claim)
            for claim in getattr(settings, "OIDC_STORE_CLAIMS", [])
        }
        return {
            "full_name": self.compute_full_name(user_info),
            "claims": claims_to_store,
        }

    def get_existing_user(self, sub, email):
        """Get an existing user by sub or email."""
        try:
            return User.objects.get_user_by_sub_or_email(sub, email)
        except DuplicateEmailError as err:
            raise SuspiciousOperation(err.message) from err
