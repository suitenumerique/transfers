"""DeployCenter Entitlements Backend."""

import logging
import time

from django.core.cache import cache

import requests

from core.entitlements import EntitlementsUnavailableError
from core.entitlements.backends.base import EntitlementsBackend

logger = logging.getLogger(__name__)

ENTITLEMENTS_CACHE_KEY_PREFIX = "entitlements:user:"
# Serve a cached answer up to this long when DeployCenter is unreachable. Kept
# above SESSION_COOKIE_AGE so a logged-in user's access is never re-decided
# against a down service mid-session.
DEFAULT_STALE_TIMEOUT = 24 * 60 * 60


class DeployCenterEntitlementsBackend(EntitlementsBackend):
    """Entitlements backend that checks permissions via a DeployCenter service."""

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        base_url,
        service_id,
        api_key,
        cache_timeout=10,
        stale_timeout=DEFAULT_STALE_TIMEOUT,
        oidc_claims=None,
        claim_defaults=None,
    ):
        self.base_url = base_url
        self.service_id = service_id
        self.api_key = api_key
        self.cache_timeout = cache_timeout
        self.stale_timeout = stale_timeout
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
            "account_type": "user",
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
            timeout=(2, 5),
        )
        response.raise_for_status()
        return response.json()

    def get_entitlements(self, user):
        """Return DeployCenter entitlements for a user, cached, stale-if-error.

        The per-user cache entry keeps the last payload and the time it was
        fetched. A value younger than ``cache_timeout`` is served as-is; an
        older one triggers a refetch, and if DeployCenter is unreachable the
        previous payload is served (up to ``stale_timeout``) so an outage does
        not lock users out. Only when nothing is cached does an outage surface
        as ``EntitlementsUnavailableError`` — the caller then fails closed.
        """
        cache_key = f"{ENTITLEMENTS_CACHE_KEY_PREFIX}{user.id}"
        entry = cache.get(cache_key)
        # Ignore entries that don't match the current schema (e.g. left over
        # from a previous version) so we never read a missing field.
        if not (
            isinstance(entry, dict) and "fetched_at" in entry and "payload" in entry
        ):
            entry = None

        if entry and time.time() - entry["fetched_at"] < self.cache_timeout:
            return entry["payload"]

        try:
            payload = self.fetch_entitlements(user)
        except requests.RequestException as exc:
            if entry is not None:
                logger.warning("DeployCenter unreachable, serving stale entitlements")
                return entry["payload"]
            logger.warning(
                "DeployCenter entitlements fetch failed: %s", type(exc).__name__
            )
            raise EntitlementsUnavailableError(
                "DeployCenter entitlements request failed."
            ) from exc

        cache.set(
            cache_key,
            {"payload": payload, "fetched_at": time.time()},
            timeout=self.stale_timeout,
        )
        return payload

    def can_access(self, user):
        """Check if a user can access the app."""
        entitlements = self.get_entitlements(user).get("entitlements", {})
        return {
            "result": entitlements.get("can_access", False),
            "reason": entitlements.get("can_access_reason"),
        }
