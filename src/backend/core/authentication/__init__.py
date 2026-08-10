"""Custom authentication classes for the transferts core app."""

# Session key carrying why a login failed, read by the OIDC callback to pick
# the ``/errors?reason=`` redirect. Holds one of the LOGIN_ERROR_* slugs below.
OIDC_ACCESS_DENIED_SESSION_KEY = "oidc_login_error"

# Entitlements denied access outright (no Drive subscription, unknown siret).
LOGIN_ERROR_ACCESS_DENIED = "access_denied"
# The entitlements service could not be reached to decide — transient.
LOGIN_ERROR_UNAVAILABLE = "unavailable"


class UserCannotAccessApp(Exception):
    """Raised when entitlements deny application access for an authenticated user."""
