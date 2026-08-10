"""
Test the DeployCenter entitlements backend.
"""

import urllib.parse

from django.core.cache import cache

import pytest
import requests
import responses

from core.entitlements import EntitlementsUnavailableError
from core.entitlements.backends.deploycenter import (
    ENTITLEMENTS_CACHE_KEY_PREFIX,
    DeployCenterEntitlementsBackend,
)
from core.factories import UserFactory

pytestmark = pytest.mark.django_db

# DeployCenter's own entitlements endpoint, which this backend consumes.
DEPLOYCENTER_URL = "http://deploycenter:8000/api/v1.0/entitlements/"
BACKEND_PARAMETERS = {
    "base_url": DEPLOYCENTER_URL,
    "api_key": "test-api-key",
    "service_id": 8,
    "oidc_claims": ["siret"],
}


def _backend(**overrides):
    return DeployCenterEntitlementsBackend(**{**BACKEND_PARAMETERS, **overrides})


def _query_of(call):
    return urllib.parse.parse_qs(urllib.parse.urlparse(call.request.url).query)


def _answer(can_access, reason=None):
    entitlements = {"can_access": can_access}
    if reason is not None:
        entitlements["can_access_reason"] = reason
    responses.add(
        responses.GET,
        DEPLOYCENTER_URL,
        json={"entitlements": entitlements},
        status=200,
    )


@responses.activate
def test_can_access_true_sends_the_expected_request():
    """A granted user gets ``result: True``, and DeployCenter gets every param."""
    _answer(True)
    user = UserFactory()
    user.claims = {"siret": "21140001500015"}

    assert _backend().can_access(user) == {"result": True, "reason": None}

    assert len(responses.calls) == 1
    query = _query_of(responses.calls[0])
    assert query["siret"] == ["21140001500015"]
    assert query["service_id"] == ["8"]
    assert query["account_type"] == ["user"]
    assert query["account_id"] == [str(user.pk)]
    assert query["account_email"] == [user.email]
    assert responses.calls[0].request.headers["X-Service-Auth"] == (
        "Bearer test-api-key"
    )


@responses.activate
def test_can_access_false_carries_the_reason():
    """A denied user gets ``result: False`` and DeployCenter's reason."""
    _answer(False, reason="not_activated")
    user = UserFactory()
    user.claims = {"siret": "12345678901234"}

    assert _backend().can_access(user) == {
        "result": False,
        "reason": "not_activated",
    }
    assert len(responses.calls) == 1


@responses.activate
def test_entitlements_are_cached_per_user():
    """A second check within the TTL must not hit DeployCenter again."""
    _answer(True)
    user = UserFactory()
    user.claims = {"siret": "12345678901234"}
    backend = _backend()

    assert backend.can_access(user) == {"result": True, "reason": None}
    assert backend.can_access(user) == {"result": True, "reason": None}

    assert len(responses.calls) == 1


@responses.activate
def test_legacy_cache_entry_is_ignored():
    """An entry from a previous cache schema is treated as a miss, not read blindly."""
    _answer(True)
    user = UserFactory()
    user.claims = {"siret": "12345678901234"}
    # Pre-upgrade entries stored the raw entitlements dict, without fetched_at.
    cache.set(
        f"{ENTITLEMENTS_CACHE_KEY_PREFIX}{user.id}",
        {"entitlements": {"can_access": True}},
    )

    assert _backend().can_access(user) == {"result": True, "reason": None}
    # The legacy entry was ignored and a fresh fetch happened.
    assert len(responses.calls) == 1


@responses.activate
def test_stale_entitlements_served_when_deploycenter_unreachable():
    """A primed cache survives a DeployCenter outage instead of failing."""
    _answer(True)
    user = UserFactory()
    user.claims = {"siret": "12345678901234"}
    # cache_timeout=0 forces every read to revalidate against DeployCenter.
    backend = _backend(cache_timeout=0)

    assert backend.can_access(user) == {"result": True, "reason": None}

    # DeployCenter now fails; the primed value must still come back.
    responses.replace(
        responses.GET, DEPLOYCENTER_URL, body=requests.ConnectionError("boom")
    )
    assert backend.can_access(user) == {"result": True, "reason": None}


def test_no_cache_and_deploycenter_down_fails_closed():
    """With nothing cached, an outage surfaces as EntitlementsUnavailableError."""
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, DEPLOYCENTER_URL, body=requests.ConnectionError("boom"))
        user = UserFactory()
        user.claims = {"siret": "12345678901234"}
        with pytest.raises(EntitlementsUnavailableError):
            _backend().can_access(user)


@responses.activate
def test_siret_falls_back_to_claim_defaults():
    """When User.claims has no siret, claim_defaults still satisfies DeployCenter."""
    _answer(True)
    user = UserFactory()
    user.claims = {}

    _backend(claim_defaults={"siret": "21140001500015"}).can_access(user)

    assert _query_of(responses.calls[0])["siret"] == ["21140001500015"]


def test_missing_siret_raises():
    """Without siret in claims or claim_defaults, the call fails fast."""
    user = UserFactory()
    user.claims = {}

    with pytest.raises(EntitlementsUnavailableError, match="siret"):
        _backend().fetch_entitlements(user)


def test_missing_base_url_parameter():
    """Missing base_url parameter should raise an exception."""
    with pytest.raises(TypeError):
        DeployCenterEntitlementsBackend(  # pylint: disable=no-value-for-parameter
            service_id=8,
            api_key="secret",
        )


def test_missing_api_key_parameter():
    """Missing api_key parameter should raise an exception."""
    with pytest.raises(TypeError):
        DeployCenterEntitlementsBackend(  # pylint: disable=no-value-for-parameter
            base_url=DEPLOYCENTER_URL,
            service_id=8,
        )


def test_missing_service_id_parameter():
    """Missing service_id parameter should raise an exception."""
    with pytest.raises(TypeError):
        DeployCenterEntitlementsBackend(  # pylint: disable=no-value-for-parameter
            base_url=DEPLOYCENTER_URL,
            api_key="secret",
        )
