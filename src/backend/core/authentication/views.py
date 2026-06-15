"""Authentication views for the transferts core app."""

from lasuite.oidc_login.views import (
    OIDCAuthenticationCallbackView as LaSuiteOIDCAuthenticationCallbackView,
)

from core.authentication import OIDC_ACCESS_DENIED_SESSION_KEY


class OIDCAuthenticationCallbackView(LaSuiteOIDCAuthenticationCallbackView):
    """OIDC callback that routes entitlement denials to the error page."""

    @property
    def failure_url(self):
        if self.request.session.pop(OIDC_ACCESS_DENIED_SESSION_KEY, False):
            return self._access_denied_redirect_url()
        return super().failure_url

    def _access_denied_redirect_url(self):
        failure_url = self.get_settings("LOGIN_REDIRECT_URL_FAILURE", "/")
        login_redirect = self.get_settings("LOGIN_REDIRECT_URL", "/")
        # Misconfigured or stale env may set failure URL to the app root — keep
        # entitlement denials on the dedicated error page.
        if failure_url.rstrip("/") == login_redirect.rstrip("/"):
            return f"{failure_url.rstrip('/')}/errors"
        return failure_url
