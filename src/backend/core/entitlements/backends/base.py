"""Entitlements Backend base class."""

from abc import ABC, abstractmethod


class EntitlementsBackend(ABC):
    """Abstract base class for entitlements backends."""

    @abstractmethod
    def can_access(self, user):
        """
        Check if a user can access app.
        """

    def get_context(self, user):  # pylint: disable=unused-argument
        """Get context for a user."""
        return {}
