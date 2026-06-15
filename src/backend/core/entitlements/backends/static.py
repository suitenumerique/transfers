"""Static Entitlements Backend."""

from core.entitlements.backends.base import EntitlementsBackend


class StaticEntitlementsBackend(EntitlementsBackend):
    """Entitlements backend that returns the static values passed to its constructor."""

    def __init__(self, entitlements=None):
        self.entitlements = entitlements or {
            "can_access": {"result": True},
        }

    def can_access(self, user):
        return self.entitlements["can_access"]
