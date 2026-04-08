"""Authentication Backends for the transferts core app."""

import logging

from django.core.exceptions import SuspiciousOperation

from lasuite.oidc_login.backends import (
    OIDCAuthenticationBackend as LaSuiteOIDCAuthenticationBackend,
)

from core.models import DuplicateEmailError, User

logger = logging.getLogger(__name__)


class OIDCAuthenticationBackend(LaSuiteOIDCAuthenticationBackend):
    """Custom OIDC Authentication Backend.

    Handles user creation/update from OIDC claims (ProConnect).
    """

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

        return user

    def get_extra_claims(self, user_info):
        """Get extra claims from user info."""
        return {
            "full_name": self.compute_full_name(user_info),
        }

    def get_existing_user(self, sub, email):
        """Get an existing user by sub or email."""
        try:
            return User.objects.get_user_by_sub_or_email(sub, email)
        except DuplicateEmailError as err:
            raise SuspiciousOperation(err.message) from err
