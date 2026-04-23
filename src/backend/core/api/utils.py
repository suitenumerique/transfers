"""API utility functions for the transferts core app."""

from core import models
from core.enums import ActorType


def log_agent_event(transfer, event_type, request):
    """Emit a ``TransferEvent`` attributed to the authenticated agent issuing
    ``request``. Used by the Transfer and TransferDraft viewsets whenever a
    user-initiated action needs to be journaled on a transfer."""
    models.TransferEvent.objects.create(
        transfer_id=transfer.id,
        event_type=event_type,
        actor_type=ActorType.AGENT,
        actor_id=request.user.id,
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
