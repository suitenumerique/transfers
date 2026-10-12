"""DRF authentication for the API."""

from rest_framework.authentication import SessionAuthentication


class SessionAuthenticationWith401(SessionAuthentication):
    """Session auth that answers an anonymous call with 401, not 403.

    DRF only sends 401 when the first authentication class names a
    ``WWW-Authenticate`` challenge; plain session auth has none, so every
    unauthenticated call would become a 403. The frontend reads 401 as
    "session gone, back to sign-in", so keep it.
    """

    def authenticate_header(self, request):
        return 'Session realm="api"'
