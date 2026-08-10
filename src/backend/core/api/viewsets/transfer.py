"""API ViewSet for Transfer (authenticated agent, read + deactivate + purge).

All the draft / upload lifecycle lives on ``TransferDraftViewSet``. Once a
draft is finalized, the resulting ``Transfer`` row is immutable except for
``deactivate`` (which closes the link immediately and schedules the S3
purge via ``pending_deletion_at`` — the sweep task handles the final
transition to DEACTIVATED) and a subsequent hard-delete (irreversible,
allowed only once the row has reached DEACTIVATED so no S3 bytes end up
orphaned by the operation).
"""

import logging

from django.db.models import Count, Exists, OuterRef, Sum

import rest_framework as drf
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action

logger = logging.getLogger(__name__)

from core import models
from core.api.permissions import IsAuthenticated
from core.api.serializers import (
    TransferDetailSerializer,
    TransferEventSerializer,
    TransferListSerializer,
)
from core.api.utils import log_agent_event
from core.api.viewsets import Pagination
from core.enums import (
    DeactivationReason,
    SharingMode,
    TransferEventType,
    TransferStatus,
)


class TransferViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only view over finalized transfers plus the ``deactivate`` transition.

    All the pre-finalize lifecycle (draft creation, file add/remove, upload
    signing, multipart completion, finalize) lives on ``TransferDraftViewSet``
    at ``/drafts/``. By construction every row in ``Transfer`` here carries
    real metadata and a public token — there is no "draft Transfer" notion
    anymore.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = Pagination

    def get_serializer_class(self):
        if self.action == "list":
            return TransferListSerializer
        if self.action == "events":
            return TransferEventSerializer
        return TransferDetailSerializer

    # Cap search query length to keep ILIKE bounded and guard against a
    # pathologically long input. Anything beyond this is a client bug.
    SEARCH_MAX_LENGTH = 100

    def get_queryset(self):
        if self.action == "list":
            qs = models.Transfer.objects.filter(owner=self.request.user)

            # ``deactivated`` bucket — "active" section = status ACTIVE only;
            # "deactivated" section = every other status (EXPIRED, DEACTIVATED).
            # Omitted → no status filter, for any caller that still wants
            # the full list.
            deactivated = self.request.query_params.get("deactivated")
            if deactivated == "true":
                qs = qs.exclude(status=TransferStatus.ACTIVE)
            elif deactivated == "false":
                qs = qs.filter(status=TransferStatus.ACTIVE)

            search = (self.request.query_params.get("search") or "").strip()
            if search:
                qs = qs.filter(title__icontains=search[: self.SEARCH_MAX_LENGTH])

            # Annotate everything the list serializer needs in one query
            # rather than prefetch + N×2 existence checks.
            event_of_type = lambda ev: Exists(
                models.TransferEvent.objects.filter(
                    transfer_id=OuterRef("pk"), event_type=ev
                )
            )
            return qs.annotate(
                _file_count=Count("files"),
                _total_size=Sum("files__size", default=0),
                _consulted=event_of_type(TransferEventType.LINK_OPENED),
                _downloaded=event_of_type(TransferEventType.FILE_DOWNLOADED),
            ).order_by("-created_at")
        return (
            models.Transfer.objects.filter(owner=self.request.user)
            .prefetch_related("files", "recipients")
            .order_by("-created_at")
        )

    def perform_destroy(self, instance):
        """Hard-delete a transfer past its ACTIVE phase.

        Two eligible states:

        * ``PENDING_FILE_DELETION`` — link is already closed but S3
          objects still exist, waiting for the grace window to elapse.
          Skip the grace and wipe now, then drop the row. Otherwise the
          purge task would try to reclaim keys whose ``TransferFile``
          rows we've already deleted and log a spurious "failed to
          purge" against a Transfer row that no longer exists.
        * ``DEACTIVATED`` — S3 was already wiped by the periodic sweep.
          Just drop the row.

        ``ACTIVE`` is refused: the link is live and killing it silently
        would surprise the recipient. The agent must click Deactivate
        first — that's the explicit "the link is going away" step. The
        frontend hides the button on ACTIVE; this backend guard is
        defense in depth for anyone crafting a raw DELETE.

        Owner-only gating rides on ``get_queryset``.

        S3 wipe is best-effort — if any object fails to delete, we
        refuse the destroy (returning 400 rather than silently orphaning
        bytes the periodic sweep can no longer reclaim). The user can
        retry after transient S3 hiccups clear.

        FK cascade carries off ``TransferFile`` and ``TransferRecipient``.
        ``TransferEvent``, deliberately not FK-constrained (see its
        docstring), stays behind — its audit trail (who sent, who
        downloaded, when) outlives the Transfer row on purpose. We log at
        INFO *after* the delete succeeds so a failure doesn't leave a
        misleading success record, and without user identifiers — actor
        attribution needs the privacy-reviewed audit pipeline, not an
        infra log line.
        """
        if instance.status == TransferStatus.ACTIVE:
            # Expected defensive rejection: the frontend hides the button on
            # ACTIVE, so reaching here means a raw DELETE (curl / script /
            # ops probe). Log at INFO — the guard fired as designed, this
            # is not a pattern that needs investigation. Include the
            # transfer id for correlation; no user identifier here (actor
            # attribution stays in the audit pipeline).
            logger.info(
                "Refused hard-delete of ACTIVE transfer %s", instance.id
            )
            raise drf.exceptions.ValidationError(
                {
                    "status": (
                        "An active transfer cannot be hard-deleted. "
                        "Deactivate it first, then delete."
                    )
                }
            )
        # PENDING_FILE_DELETION still owns bytes — wipe them before the
        # row goes so the periodic sweep never finds orphan keys.
        if instance.status == TransferStatus.PENDING_FILE_DELETION:
            if not instance.delete_s3_objects():
                # Storage failure (S3 hiccup, credentials rot, bucket
                # policy change) — WARNING so ops sees the rate. The
                # user retries; we refuse rather than orphan bytes the
                # sweep can no longer reclaim. The user-facing message
                # stays generic on purpose: PENDING_FILE_DELETION is
                # rendered as "Deactivated" in the UI (the grace window
                # is invisible) and the deactivate confirm already
                # promised "files will be deleted" — mentioning "some
                # files could not be deleted from storage" here would
                # contradict that promise and confuse the user.
                logger.warning(
                    "Refused hard-delete of transfer %s: S3 cleanup failed",
                    instance.id,
                )
                raise drf.exceptions.ValidationError(
                    {
                        "detail": (
                            "This transfer can't be deleted right now. "
                            "Try again in a moment."
                        )
                    }
                )
        transfer_id = instance.id
        instance.delete()
        logger.info("Transfer %s hard-deleted", transfer_id)

    @extend_schema(responses={200: TransferDetailSerializer})
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate a transfer — closes the link immediately and schedules
        the S3 purge ``TRANSFER_PURGE_DELAY_HOURS`` later. Mirrors the
        first-download and expiry flows: the grace window lets recipients'
        in-flight downloads finish before the bytes disappear. The final
        ``PENDING_FILE_DELETION → DEACTIVATED`` transition is handled by
        ``delete_pending_transfer_files_task``.
        """
        transfer = self.get_object()

        if transfer.status != TransferStatus.ACTIVE:
            raise drf.exceptions.ValidationError(
                {"status": "Only active transfers can be deactivated."}
            )

        transfer.deactivate(DeactivationReason.MANUAL)

        log_agent_event(
            transfer, TransferEventType.TRANSFER_DEACTIVATED_MANUALLY, request
        )

        serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(serializer.data)

    @extend_schema(responses={200: TransferDetailSerializer})
    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        """Retry failed recipient invitation emails for an email-mode
        transfer. The task only emails recipients with
        ``email_sent_at IS NULL``, so calling it again is the natural retry
        path — a successful first send leaves nothing to do.

        ``notifications_completed_at`` is cleared so the frontend can poll
        until the task stamps it again, signalling the retry has finished.
        """
        from core.tasks import send_recipient_invitations_task

        transfer = self.get_object()

        if transfer.status != TransferStatus.ACTIVE:
            raise drf.exceptions.ValidationError(
                {"status": "Only active transfers can be re-sent."}
            )
        if transfer.sharing_mode != SharingMode.EMAIL:
            raise drf.exceptions.ValidationError(
                {"sharing_mode": "Resend only applies to email-mode transfers."}
            )

        transfer.notifications_completed_at = None
        transfer.save(update_fields=["notifications_completed_at", "updated_at"])
        send_recipient_invitations_task.delay(str(transfer.id))

        serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(serializer.data)

    @extend_schema(responses={200: TransferEventSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        """List events for a transfer."""
        transfer = self.get_object()
        events = models.TransferEvent.objects.filter(transfer_id=transfer.id).order_by(
            "-created_at"
        )
        page = self.paginate_queryset(events)
        if page is not None:
            serializer = TransferEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = TransferEventSerializer(events, many=True)
        return drf.response.Response(serializer.data)
