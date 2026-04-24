"""API ViewSet for Transfer (authenticated agent, read-only + deactivate).

All the draft / upload lifecycle lives on ``TransferDraftViewSet``. Once a
draft is finalized, the resulting ``Transfer`` row is immutable except for
``deactivate`` (which transitions it to the DEACTIVATED status and tears
down S3 objects). Listing / retrieving / inspecting events happen here;
mutation beyond deactivate does not exist.
"""

from django.db.models import Count, Exists, OuterRef, Sum
from django.utils import timezone

import rest_framework as drf
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action

from core import models
from core.api.permissions import IsAuthenticated
from core.api.serializers import (
    TransferDetailSerializer,
    TransferEventSerializer,
    TransferListSerializer,
)
from core.api.utils import log_agent_event
from core.api.viewsets import Pagination
from core.enums import SharingMode, TransferEventType, TransferStatus


class TransferViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
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

    @extend_schema(responses={200: TransferDetailSerializer})
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate a transfer — flips its status to DEACTIVATED and
        tears down the underlying S3 objects. Only valid on an active
        transfer.
        """
        transfer = self.get_object()

        if transfer.status != TransferStatus.ACTIVE:
            raise drf.exceptions.ValidationError(
                {"status": "Only active transfers can be deactivated."}
            )

        transfer.delete_s3_objects()

        transfer.status = TransferStatus.DEACTIVATED
        transfer.deactivated_at = timezone.now()
        transfer.save(update_fields=["status", "deactivated_at", "updated_at"])

        log_agent_event(transfer, TransferEventType.TRANSFER_DEACTIVATED, request)

        serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(serializer.data)

    @extend_schema(responses={200: TransferDetailSerializer})
    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        """Re-send the recipient invitation emails for an email-mode
        transfer. No-op on link-mode transfers (no recipients).

        Stamps `email_sent_at` back to NULL on each recipient before
        delegating to the existing celery task — the task only emails
        recipients with `email_sent_at IS NULL`, so a reset is the most
        precise trigger.
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

        transfer.recipients.update(email_sent_at=None)
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
