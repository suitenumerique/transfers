"""Custom authentication classes for the transferts core app."""

OIDC_ACCESS_DENIED_SESSION_KEY = "oidc_access_denied"


class UserCannotAccessApp(Exception):
    """Raised when entitlements deny application access for an authenticated user."""
