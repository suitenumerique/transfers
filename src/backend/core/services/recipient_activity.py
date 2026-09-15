"""Per-recipient activity, derived from the event log.

Every recipient of an email-mode transfer gets the same public link plus a
personal ``?r=<token>``; the download views stamp ``recipient_id`` on the
LINK_OPENED / FILE_DOWNLOADED events they record when that token is
present. This module folds those events back into one record per
recipient: when they first opened the link, when they last downloaded,
and which files they have fetched so far. Nothing here is stored — the
event log stays the source of truth.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from core.enums import TransferEventType
from core.models import TransferEvent


@dataclass
class RecipientActivity:
    opened_at: datetime | None = None
    downloaded_at: datetime | None = None
    downloaded_file_ids: set[str] = field(default_factory=set)


def activity_by_recipient(transfer_id) -> dict[UUID, RecipientActivity]:
    """One query for the whole transfer — the detail page lists up to 50
    recipients and must not fan out per row."""
    rows = (
        TransferEvent.objects.filter(
            transfer_id=transfer_id,
            recipient_id__isnull=False,
            event_type__in=[
                TransferEventType.LINK_OPENED,
                TransferEventType.FILE_DOWNLOADED,
            ],
        )
        .order_by("created_at")
        .values_list("recipient_id", "event_type", "created_at", "payload")
    )
    activity: dict[UUID, RecipientActivity] = {}
    # Rows come in chronological order, so: the first LINK_OPENED wins
    # (never overwritten) and the last FILE_DOWNLOADED wins (always
    # overwritten). "Opened on" is when they first showed up; "downloaded
    # on" is their most recent fetch.
    for recipient_id, event_type, created_at, payload in rows:
        entry = activity.setdefault(recipient_id, RecipientActivity())
        if event_type == TransferEventType.LINK_OPENED:
            if entry.opened_at is None:
                entry.opened_at = created_at
        else:
            entry.downloaded_at = created_at
            file_id = (payload or {}).get("file_id")
            if file_id:
                entry.downloaded_file_ids.add(str(file_id))
    return activity


def files_downloaded_by(transfer_id, recipient_id) -> set[str]:
    """Distinct file ids this recipient has fetched at least once."""
    file_ids = (
        TransferEvent.objects.filter(
            transfer_id=transfer_id,
            recipient_id=recipient_id,
            event_type=TransferEventType.FILE_DOWNLOADED,
            payload__file_id__isnull=False,
        )
        .values_list("payload__file_id", flat=True)
        .distinct()
    )
    return {str(f) for f in file_ids}


def activity_for(transfer_id, recipient_id) -> RecipientActivity:
    """One recipient's folded activity (empty record if none). Accepts the
    id as a UUID or its string form — Celery task args arrive as strings,
    while the map is keyed by the UUIDs the query returns."""
    key = recipient_id if isinstance(recipient_id, UUID) else UUID(str(recipient_id))
    return activity_by_recipient(transfer_id).get(key) or RecipientActivity()
