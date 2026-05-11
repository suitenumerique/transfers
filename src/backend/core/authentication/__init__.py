"""Custom authentication classes for the transferts core app."""


class UserCannotAccessApp(Exception):
    """Raised when entitlements deny application access for an authenticated user."""
