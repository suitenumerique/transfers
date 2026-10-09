"""
Login gate: entitlements decide who authenticates, and a failed login carries
why it failed so the error page can tell the user (offer excludes the service
vs. the check could not run).
"""

import types
from unittest import mock

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
from core.authentication import backends as auth_backends
from core.authentication.backends import OIDCAuthenticationBackend
from core.authentication.views import OIDCAuthenticationCallbackView
from core.entitlements import EntitlementsUnavailableError
from core.factories import UserFactory

pytestmark = pytest.mark.django_db

STATIC_BACKEND = "core.entitlements.backends.static.StaticEntitlementsBackend"


class _Session(dict):
    """Minimal stand-in for a Django session: a dict that tracks ``modified``."""

    modified = False

    def save(self):
        """Sessions are saved by the base silent-login branch."""


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


@override_settings(
    OIDC_OP_JWKS_ENDPOINT="http://oidc.test/jwks",
    OIDC_STORE_CLAIMS=["siret"],
    ENTITLEMENTS_BACKEND=STATIC_BACKEND,
    ENTITLEMENTS_BACKEND_PARAMETERS=_static_params({"result": True}),
)
def test_login_clears_a_claim_the_idp_stopped_sending():
    """A claim gone from userinfo is removed from User.claims, not kept stale."""
    user = UserFactory(claims={"siret": "12345678901234"})
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
        backend.get_or_create_user("access", "id", {})

    user.refresh_from_db()
    assert user.claims == {}


@override_settings(
    OIDC_OP_JWKS_ENDPOINT="http://oidc.test/jwks",
    OIDC_STORE_CLAIMS=["siret"],
    ENTITLEMENTS_BACKEND=STATIC_BACKEND,
    ENTITLEMENTS_BACKEND_PARAMETERS=_static_params({"result": True}),
)
def test_login_updates_claims_without_logging_their_values(caplog):
    """A changed claim is persisted, and its values stay out of the logs."""
    user = UserFactory(claims={"siret": "12345678901234"})
    backend = OIDCAuthenticationBackend()
    with mock.patch.object(
        backend,
        "get_userinfo",
        return_value={
            "sub": user.sub,
            "email": user.email,
            "given_name": "A",
            "family_name": "B",
            "siret": "98765432109876",
        },
    ):
        with (
            caplog.at_level("INFO"),
            mock.patch.object(auth_backends.logger, "info") as info,
        ):
            backend.get_or_create_user("access", "id", {})

    user.refresh_from_db()
    assert user.claims == {"siret": "98765432109876"}
    assert "12345678901234" not in caplog.text
    assert "98765432109876" not in caplog.text
    # caplog holds the base backend's logs; ours is checked on its own logger.
    assert info.called
    assert str(user.pk) not in str(info.call_args_list)
    assert "98765432109876" not in str(info.call_args_list)


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
    with (
        mock.patch.object(
            LaSuiteBackend,
            "authenticate",
            side_effect=UserCannotAccessApp("not_activated"),
        ),
        # Asserted on the module logger: ``core`` does not propagate to caplog.
        mock.patch.object(auth_backends.logger, "info") as info,
    ):
        assert _backend_without_init().authenticate(request) is None
    # DeployCenter's reason is provider text: it stays out of the logs.
    assert info.called
    assert "not_activated" not in str(info.call_args_list)
    assert request.session[OIDC_ACCESS_DENIED_SESSION_KEY] == LOGIN_ERROR_ACCESS_DENIED
    assert request.session.modified is True


@pytest.mark.parametrize("signed_in", [True, False])
def test_denial_signs_out_a_previous_session(signed_in):
    """A denied re-login must not leave an earlier session signed in."""
    request = _request()
    request.user = mock.Mock(is_authenticated=signed_in)
    with (
        mock.patch.object(
            LaSuiteBackend, "authenticate", side_effect=UserCannotAccessApp("x")
        ),
        mock.patch.object(auth_backends.auth, "logout") as logout,
    ):
        assert _backend_without_init().authenticate(request) is None
    assert logout.called is signed_in
    assert request.session[OIDC_ACCESS_DENIED_SESSION_KEY] == LOGIN_ERROR_ACCESS_DENIED


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


@override_settings(
    LOGIN_REDIRECT_URL_FAILURE="http://localhost:8980/errors",
    LOGIN_REDIRECT_URL="http://localhost:8980",
)
def test_failure_url_on_silent_login_goes_home_and_clears_the_flag():
    """A silent login denied by entitlements stays silent, like any silent failure."""
    view = OIDCAuthenticationCallbackView()
    view.request = _request(
        _Session(
            {OIDC_ACCESS_DENIED_SESSION_KEY: LOGIN_ERROR_ACCESS_DENIED, "silent": True}
        )
    )

    assert view.failure_url == view.success_url
    assert "silent" not in view.request.session
    assert OIDC_ACCESS_DENIED_SESSION_KEY not in view.request.session
