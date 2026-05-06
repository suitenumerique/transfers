"""
Test Entitlements API endpoints.
"""

from unittest import mock

import pytest
from rest_framework.test import APIClient

from core.factories import UserFactory
from core.entitlements import get_entitlements_backend

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_entitlements_backend_cache():
    # get_entitlements_backend() is cached via functools.cache; clear between tests
    # so overrides/settings mutations are always applied.
    get_entitlements_backend.cache_clear()
    yield
    get_entitlements_backend.cache_clear()


def test_api_entitlements_get_entitlements_anonymous():
    """Anonymous users should not be allowed to get entitlements."""
    client = APIClient()
    response = client.get("/api/v1.0/entitlements/")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication credentials were not provided."}


def test_api_entitlements_get_entitlements_authenticated():
    """Authenticated users should be allowed to get entitlements."""
    client = APIClient()
    user = UserFactory()
    client.force_authenticate(user)
    response = client.get("/api/v1.0/entitlements/")
    assert response.status_code == 200
    assert response.json() == {
        "can_access": {
            "result": True,
        },
        "can_upload": {
            "result": True,
        },
        "context": {},
    }


def test_api_entitlements_static_backend_reads_from_parameters(settings):
    """StaticEntitlementsBackend should return values from ENTITLEMENTS_BACKEND_PARAMETERS."""
    settings.ENTITLEMENTS_BACKEND_PARAMETERS = {
        "entitlements": {
            "can_access": {"result": False, "message": "Access denied for testing"},
            "can_upload": {"result": False, "message": "Upload denied for testing"},
        },
    }
    get_entitlements_backend.cache_clear()

    client = APIClient()
    user = UserFactory()
    client.force_authenticate(user)
    response = client.get("/api/v1.0/entitlements/")

    assert response.status_code == 200
    assert response.json() == {
        "can_access": {"result": False, "message": "Access denied for testing"},
        "can_upload": {"result": False, "message": "Upload denied for testing"},
        "context": {},
    }


def test_api_entitlements_get_entitlements_entitlements_backend_returns_falsy():
    """Authenticated users should be allowed to get entitlements with a custom message."""
    real_backend = get_entitlements_backend()
    real_backend.can_access = mock.Mock(
        return_value={"result": False, "message": "You do not have access to the app"}
    )

    with mock.patch(
        "core.api.viewsets.entitlements.get_entitlements_backend",
        return_value=real_backend,
    ):
        client = APIClient()
        user = UserFactory()
        client.force_authenticate(user)
        response = client.get("/api/v1.0/entitlements/")
        assert response.status_code == 200
        assert response.json() == {
            "can_access": {
                "result": False,
                "message": "You do not have access to the app",
            },
            "can_upload": {
                "result": True,
            },
            "context": {},
        }
