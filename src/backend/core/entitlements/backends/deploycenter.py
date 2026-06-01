"""DeployCenter Entitlements Backend."""

import logging

from django.core.cache import cache

import requests

from core.entitlements import EntitlementsUnavailableError
from core.entitlements.backends.base import EntitlementsBackend

logger = logging.getLogger(__name__)

ENTITLEMENTS_CACHE_TIMEOUT = 60
ENTITLEMENTS_CACHE_KEY_PREFIX = "entitlements:user:"


class DeployCenterEntitlementsBackend(EntitlementsBackend):
    """Entitlements backend that checks permissions via a DeployCenter service."""

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        base_url,
        service_id,
        api_key,
        cache_timeout=10,
        oidc_claims=None,
        claim_defaults=None,
    ):
        self.base_url = base_url
        self.service_id = service_id
        self.api_key = api_key
        self.cache_timeout = cache_timeout
        self.oidc_claims = oidc_claims or []
        self.claim_defaults = claim_defaults or {}

    def fetch_entitlements(self, user):
        """Fetch entitlements for a user from the DeployCenter service.

        Query shape matches DeployCenter expectations, e.g.::

            ?service_id=1&siret=...&account_type=user
            &account_id=<uuid>&account_email=...

        ``siret`` (and other ``oidc_claims``) come from ``User.claims``, then
        ``claim_defaults`` (see ``ENTITLEMENTS_BACKEND_PARAMETERS``).

        DeployCenter's ``EntitlementViewSerializer`` marks ``siret`` as
        **required** — we always send it when a value exists from claims or
        defaults, otherwise we fail fast with a clear error.
        """
        params = {
            "service_id": self.service_id,
            "account_type": "email",
            "account_id": str(user.pk),
            "account_email": user.email or "",
        }

        stored = getattr(user, "claims", None) or {}

        def claim_value(name: str):
            if isinstance(stored, dict):
                raw = stored.get(name)
                if raw not in (None, ""):
                    return raw
            fallback = self.claim_defaults.get(name)
            if fallback not in (None, ""):
                return fallback
            return None

        for claim in self.oidc_claims:
            value = claim_value(claim)
            if value is not None:
                params[claim] = value

        if "siret" not in params:
            siret = claim_value("siret")
            if siret is not None:
                params["siret"] = siret

        if "siret" not in params:
            raise EntitlementsUnavailableError(
                "DeployCenter entitlements require a `siret` query parameter. "
                "Provide it via OIDC userinfo → User.claims (and OIDC_STORE_CLAIMS), "
                "or set ENTITLEMENTS_BACKEND_PARAMETERS['claim_defaults'] "
                'e.g. {"siret": "21140001500015"} for local/dev.'
            )

        response = requests.get(
            self.base_url,
            params=params,
            headers={"X-Service-Auth": f"Bearer {self.api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def get_entitlements(self, user):
        """Get entitlements for a user, cached."""
        cache_key = f"{ENTITLEMENTS_CACHE_KEY_PREFIX}{user.id}"
        entitlements = cache.get(cache_key)
        if entitlements:
            return entitlements
        try:
            entitlements = self.fetch_entitlements(user)
        except requests.RequestException:
            logger.exception("Failed to fetch entitlements for user %s", user.id)
            raise
        cache.set(cache_key, entitlements, timeout=self.cache_timeout)
        return entitlements

    def get_context(self, user):
        """Get context for a user."""
        attributes_whitelist = ["organization", "operator", "potentialOperators"]
        entitlements = self.get_entitlements(user)
        context = {}
        for attribute in attributes_whitelist:
            context[attribute] = entitlements.get(attribute)
        return context

    def can_access(self, user):
        """Check if a user can access the app."""
        entitlements = self.get_entitlements(user)
        return {"result": entitlements.get("entitlements", {}).get("can_access", False)}
