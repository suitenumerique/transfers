"""Expose session-stored dev claims as `request.user.claims`.

This is only intended for local development when `DEV_AUTH_BYPASS` is enabled.
The dev-login endpoint stores minimal claims in the session, and this middleware
hydrates them onto the authenticated user object so code paths that expect OIDC
claims can keep working (e.g. entitlements backends).
"""

from __future__ import annotations

from typing import Any, Callable

from django.http import HttpRequest, HttpResponse

_DEV_CLAIMS_SESSION_KEY = "dev_oidc_claims"


class DevAuthClaimsMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            if not hasattr(user, "claims"):
                claims: Any = request.session.get(_DEV_CLAIMS_SESSION_KEY, {})
                if isinstance(claims, dict):
                    setattr(user, "claims", claims)
                else:
                    setattr(user, "claims", {})
        return self.get_response(request)

