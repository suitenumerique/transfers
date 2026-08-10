"""Authentication views for the transferts core app."""

from lasuite.oidc_login.views import (
    OIDCAuthenticationCallbackView as LaSuiteOIDCAuthenticationCallbackView,
)

from core.authentication import OIDC_ACCESS_DENIED_SESSION_KEY


class OIDCAuthenticationCallbackView(LaSuiteOIDCAuthenticationCallbackView):
    """OIDC callback that routes entitlement outcomes to the error page.

    A generic OIDC failure (cancelled login, stale state) falls through to the
    default failure URL with no ``reason``; the error page then shows a neutral
    message rather than claiming the service is not in the user's offer.
    """

    @property
    def failure_url(self):
        reason = self.request.session.pop(OIDC_ACCESS_DENIED_SESSION_KEY, None)
        if reason:
            return self._error_redirect_url(reason)
        return super().failure_url

    def _error_redirect_url(self, reason):
        base = self.get_settings("LOGIN_REDIRECT_URL_FAILURE", "/")
        login_redirect = self.get_settings("LOGIN_REDIRECT_URL", "/")
        # Misconfigured or stale env may set the failure URL to the app root —
        # keep entitlement outcomes on the dedicated error page.
        if base.rstrip("/") == login_redirect.rstrip("/"):
            base = f"{base.rstrip('/')}/errors"
        return f"{base.rstrip('/')}?reason={reason}"
