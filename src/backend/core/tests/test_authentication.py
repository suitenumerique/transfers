"""
Login gate: entitlements decide who authenticates, and a failed login carries
why it failed so the error page can tell the user (offer excludes the service
vs. the check could not run).
"""

import types
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import override_settings

import pytest
from lasuite.oidc_login.backends import (
    OIDCAuthenticationBackend as LaSuiteBackend,
)

from core.authentication import (
    LOGIN_ERROR_ACCESS_DENIED,
    LOGIN_ERROR_UNAVAILABLE,
    OIDC_ACCESS_DENIED_SESSION_KEY,
    UserCannotAccessApp,
)
from core.authentication.backends import OIDCAuthenticationBackend
from core.authentication.dev_claims_middleware import (
    _DEV_CLAIMS_SESSION_KEY,
    DevAuthClaimsMiddleware,
)
from core.authentication.views import OIDCAuthenticationCallbackView
from core.entitlements import EntitlementsUnavailableError
from core.factories import UserFactory

pytestmark = pytest.mark.django_db

STATIC_BACKEND = "core.entitlements.backends.static.StaticEntitlementsBackend"


class _Session(dict):
    """Minimal stand-in for a Django session: a dict that tracks ``modified``."""

    modified = False


def _request(session=None):
    return types.SimpleNamespace(session=session if session is not None else _Session())


def _static_params(can_access):
    return {"entitlements": {"can_access": can_access}}


# --- The entitlements gate inside get_or_create_user ---------------------------


@override_settings(
    OIDC_OP_JWKS_ENDPOINT="http://oidc.test/jwks",
    ENTITLEMENTS_BACKEND=STATIC_BACKEND,
    ENTITLEMENTS_BACKEND_PARAMETERS=_static_params(
        {"result": False, "reason": "not_activated"}
    ),
)
def test_get_or_create_user_denied_raises_cannot_access():
    """A user the backend denies never becomes a logged-in user."""
    user = UserFactory()
    backend = OIDCAuthenticationBackend()
    with mock.patch.object(
        backend,
        "get_userinfo",
        return_value={
            "sub": user.sub,
            "email": user.email,
            "given_name": "A",
            "family_name": "B",
        },
    ):
        with pytest.raises(UserCannotAccessApp):
            backend.get_or_create_user("access", "id", {})


@override_settings(OIDC_OP_JWKS_ENDPOINT="http://oidc.test/jwks")
def test_get_or_create_user_returns_none_when_base_declines():
    """When the base backend declines (no match, creation disabled), fail
    cleanly with None rather than run the entitlements gate on a null user."""
    backend = OIDCAuthenticationBackend()
    with mock.patch.object(LaSuiteBackend, "get_or_create_user", return_value=None):
        assert backend.get_or_create_user("access", "id", {}) is None


@override_settings(
    OIDC_OP_JWKS_ENDPOINT="http://oidc.test/jwks",
    ENTITLEMENTS_BACKEND=STATIC_BACKEND,
    ENTITLEMENTS_BACKEND_PARAMETERS=_static_params({"result": True}),
)
def test_get_or_create_user_granted_returns_user():
    """A user the backend grants is returned to the OIDC flow."""
    user = UserFactory()
    backend = OIDCAuthenticationBackend()
    with mock.patch.object(
        backend,
        "get_userinfo",
        return_value={
            "sub": user.sub,
            "email": user.email,
            "given_name": "A",
            "family_name": "B",
        },
    ):
        result = backend.get_or_create_user("access", "id", {})
    assert result.pk == user.pk


# --- authenticate() maps each outcome to a login failure with a reason ---------


def _backend_without_init():
    """A backend instance that skips OIDC ``__init__`` (only authenticate is tested)."""
    return OIDCAuthenticationBackend.__new__(OIDCAuthenticationBackend)


def test_authenticate_passes_through_on_success():
    """A successful OIDC authentication returns the user and leaves the session."""
    sentinel = UserFactory()
    request = _request()
    with mock.patch.object(LaSuiteBackend, "authenticate", return_value=sentinel):
        assert _backend_without_init().authenticate(request) is sentinel
    assert OIDC_ACCESS_DENIED_SESSION_KEY not in request.session


def test_authenticate_maps_denial_to_access_denied_reason():
    """A denial fails the login and records the access-denied reason."""
    request = _request()
    with mock.patch.object(
        LaSuiteBackend, "authenticate", side_effect=UserCannotAccessApp("not_activated")
    ):
        assert _backend_without_init().authenticate(request) is None
    assert request.session[OIDC_ACCESS_DENIED_SESSION_KEY] == LOGIN_ERROR_ACCESS_DENIED
    assert request.session.modified is True


def test_authenticate_maps_outage_to_unavailable_reason():
    """An unreachable entitlements service fails the login as transient."""
    request = _request()
    with mock.patch.object(
        LaSuiteBackend, "authenticate", side_effect=EntitlementsUnavailableError("down")
    ):
        assert _backend_without_init().authenticate(request) is None
    assert request.session[OIDC_ACCESS_DENIED_SESSION_KEY] == LOGIN_ERROR_UNAVAILABLE


# --- The callback routes each reason to /errors?reason= ------------------------


@override_settings(
    LOGIN_REDIRECT_URL_FAILURE="http://localhost:8980/errors",
    LOGIN_REDIRECT_URL="http://localhost:8980",
)
@pytest.mark.parametrize("reason", [LOGIN_ERROR_ACCESS_DENIED, LOGIN_ERROR_UNAVAILABLE])
def test_failure_url_carries_and_consumes_the_reason(reason):
    view = OIDCAuthenticationCallbackView()
    view.request = _request(_Session({OIDC_ACCESS_DENIED_SESSION_KEY: reason}))

    assert view.failure_url == f"http://localhost:8980/errors?reason={reason}"
    # The reason is popped so a later unrelated failure does not reuse it.
    assert OIDC_ACCESS_DENIED_SESSION_KEY not in view.request.session


@override_settings(
    LOGIN_REDIRECT_URL_FAILURE="http://localhost:8980/errors",
    LOGIN_REDIRECT_URL="http://localhost:8980",
)
def test_failure_url_without_reason_stays_generic():
    """A plain OIDC failure (no reason) must not claim an access denial."""
    view = OIDCAuthenticationCallbackView()
    view.request = _request(_Session())

    url = view.failure_url
    assert url == "http://localhost:8980/errors"
    assert "reason=" not in url


@override_settings(
    LOGIN_REDIRECT_URL_FAILURE="http://localhost:8980",
    LOGIN_REDIRECT_URL="http://localhost:8980",
)
def test_failure_url_forces_errors_path_when_misconfigured():
    """When the failure URL is the app root, keep denials on /errors."""
    view = OIDCAuthenticationCallbackView()
    view.request = _request(
        _Session({OIDC_ACCESS_DENIED_SESSION_KEY: LOGIN_ERROR_ACCESS_DENIED})
    )

    assert view.failure_url == "http://localhost:8980/errors?reason=access_denied"


# --- Dev claims middleware hydrates request.user.claims -----------------------


def test_dev_claims_middleware_hydrates_from_session():
    """An authenticated user with no claims picks them up from the session."""
    user = UserFactory(claims={})
    request = types.SimpleNamespace(
        user=user, session={_DEV_CLAIMS_SESSION_KEY: {"siret": "21140001500015"}}
    )
    middleware = DevAuthClaimsMiddleware(lambda req: "response")

    assert middleware(request) == "response"
    assert user.claims == {"siret": "21140001500015"}


def test_dev_claims_middleware_leaves_existing_claims():
    """Claims already on the user are never overwritten."""
    user = UserFactory(claims={"siret": "real"})
    request = types.SimpleNamespace(
        user=user, session={_DEV_CLAIMS_SESSION_KEY: {"siret": "other"}}
    )
    middleware = DevAuthClaimsMiddleware(lambda req: "response")

    middleware(request)
    assert user.claims == {"siret": "real"}


def test_dev_claims_middleware_ignores_anonymous():
    """An anonymous request passes straight through."""
    request = types.SimpleNamespace(
        user=AnonymousUser(), session={_DEV_CLAIMS_SESSION_KEY: {"siret": "x"}}
    )
    middleware = DevAuthClaimsMiddleware(lambda req: "response")

    assert middleware(request) == "response"
