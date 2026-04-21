"""API ViewSet for Transfer model (authenticated agent endpoints)."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.utils import timezone

import botocore
import rest_framework as drf
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action

from core import models
from core.api.permissions import IsAuthenticated
from core.api.serializers import (
    TransferAddFileSerializer,
    TransferCompleteUploadSerializer,
    TransferDetailSerializer,
    TransferEventSerializer,
    TransferFinalizeSerializer,
    TransferListSerializer,
    TransferRemoveFileSerializer,
    TransferSignPartSerializer,
)
from core.api.viewsets import Pagination
from core.enums import ActorType, SharingMode, TransferEventType, TransferStatus
from core.models import _generate_public_token
from core.services import s3


def _log_event(transfer, event_type, request):
    """Helper to emit a TransferEvent with the request context."""
    models.TransferEvent.objects.create(
        transfer_id=transfer.id,
        event_type=event_type,
        actor_type=ActorType.AGENT,
        actor_id=request.user.id,
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


class TransferViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """ViewSet for managing transfers (authenticated agent).

    Drafts have no dedicated ``create`` endpoint — the ``add-file`` action
    doubles as the draft opener when called without a ``transfer_id``.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = Pagination

    def get_serializer_class(self):
        if self.action == "list":
            return TransferListSerializer
        if self.action == "events":
            return TransferEventSerializer
        if self.action == "sign_part":
            return TransferSignPartSerializer
        if self.action == "complete_upload":
            return TransferCompleteUploadSerializer
        if self.action == "add_file":
            return TransferAddFileSerializer
        if self.action == "remove_file":
            return TransferRemoveFileSerializer
        if self.action == "finalize":
            return TransferFinalizeSerializer
        return TransferDetailSerializer

    def get_queryset(self):
        if self.action == "list":
            # List: annotate everything the serializer needs so we run a
            # single query instead of a prefetch + N*2 existence checks +
            # Python-side filtering.
            completed_files = Q(files__upload_completed_at__isnull=False)
            event_of_type = lambda ev: Exists(
                models.TransferEvent.objects.filter(
                    transfer_id=OuterRef("pk"), event_type=ev
                )
            )
            return (
                models.Transfer.objects.filter(
                    owner=self.request.user,
                    upload_completed_at__isnull=False,
                )
                .annotate(
                    _file_count=Count("files", filter=completed_files),
                    _total_size=Sum(
                        "files__size", filter=completed_files, default=0
                    ),
                    _consulted=event_of_type(TransferEventType.LINK_OPENED),
                    _downloaded=event_of_type(TransferEventType.FILE_DOWNLOADED),
                )
                .order_by("-created_at")
            )
        return (
            models.Transfer.objects.filter(owner=self.request.user)
            .prefetch_related("files", "recipients")
            .order_by("-created_at")
        )

    def _get_pending_file(self, transfer, file_id):
        """Fetch a TransferFile belonging to ``transfer`` whose upload is in
        progress. Raises 404/400 on mismatch."""
        try:
            tf = transfer.files.get(id=file_id)
        except models.TransferFile.DoesNotExist as exc:
            raise drf.exceptions.NotFound("Transfer file not found.") from exc
        if tf.is_upload_complete:
            raise drf.exceptions.ValidationError(
                {"transfer_file_id": "Upload already completed for this file."}
            )
        if not tf.upload_id:
            raise drf.exceptions.ValidationError(
                {"transfer_file_id": "No multipart upload in progress."}
            )
        return tf

    def _check_draft(self, transfer):
        """Guard: refuse mutations on a finalized transfer.

        Used by ``add_file`` and ``remove_file`` — once the transfer has a
        ``public_token``, its file list and metadata are frozen (``revoke``
        is the only post-finalize transition).
        """
        if transfer.is_finalized:
            raise drf.exceptions.PermissionDenied(
                "Cannot modify a finalized transfer."
            )

    @extend_schema(
        request=TransferSignPartSerializer,
        responses={
            200: inline_serializer(
                name="TransferSignPartResponse",
                fields={
                    "url": serializers.URLField(),
                    "part_number": serializers.IntegerField(),
                },
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="sign-part")
    def sign_part(self, request, pk=None):
        """Return a presigned URL to upload a single part of a file."""
        transfer = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        transfer_file = self._get_pending_file(transfer, data["transfer_file_id"])
        url = s3.sign_upload_part(
            key=transfer_file.s3_key,
            upload_id=transfer_file.upload_id,
            part_number=data["part_number"],
        )
        return drf.response.Response(
            {"url": url, "part_number": data["part_number"]}
        )

    @extend_schema(
        request=TransferCompleteUploadSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="complete-upload")
    def complete_upload(self, request, pk=None):
        """Complete the S3 multipart upload for a single file.

        This is a per-file S3 verb, not a transfer-level transition. The
        transfer itself is not yet usable: the caller must call ``finalize``
        once **all** its files have been completed. Until then the transfer
        has no public token and is not listed.

        If S3 rejects the completion (wrong ETag, missing part, invalid
        order…), the whole transfer is unrecoverable: we best-effort abort
        all in-progress multipart uploads on S3 and delete the transfer.
        """
        transfer = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        transfer_file = self._get_pending_file(transfer, data["transfer_file_id"])

        try:
            s3.complete_multipart_upload(
                key=transfer_file.s3_key,
                upload_id=transfer_file.upload_id,
                parts=data["parts"],
            )
        except botocore.exceptions.ClientError as exc:
            # S3 rejected the completion — the multipart upload is
            # unrecoverable. Abort every still-pending multipart upload on
            # S3 and delete the transfer entirely (all-or-nothing semantics).
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            transfer.abort_pending_uploads()
            transfer.delete()
            raise drf.exceptions.ValidationError(
                {
                    "parts": (
                        f"S3 rejected the multipart upload completion "
                        f"({error_code}). The transfer has been aborted, "
                        f"please restart it from scratch."
                    )
                }
            ) from exc

        # Verify that what actually landed in S3 matches what the client
        # declared at create time. The presigned PUT URLs we handed out don't
        # carry a Content-Length restriction, so a malicious (or buggy)
        # client could declare a 5 KB file and upload 10 GB. We catch the
        # discrepancy here and nuke the transfer.
        #
        # TODO: this is a safety net, not a hard barrier — by the time we
        # check, the bytes have already transited our ingress and landed in
        # S3. For stricter enforcement, sign each part with a ContentLength
        # cap and track the cumulative signed bytes per TransferFile at sign
        # time, refusing any sign-part that would exceed the declared total.
        actual_size = s3.head_object_size(transfer_file.s3_key)
        if actual_size != transfer_file.size:
            transfer.abort_pending_uploads()
            transfer.delete_s3_objects()
            transfer.delete()
            raise drf.exceptions.ValidationError(
                {
                    "parts": (
                        f"Uploaded file size ({actual_size} bytes) does not "
                        f"match the declared size ({transfer_file.size} "
                        f"bytes). The transfer has been aborted."
                    )
                }
            )

        transfer_file.upload_completed_at = timezone.now()
        transfer_file.upload_id = ""
        transfer_file.save(
            update_fields=["upload_completed_at", "upload_id", "updated_at"]
        )

        return drf.response.Response(status=204)

    @extend_schema(
        request=TransferAddFileSerializer,
        responses={
            201: inline_serializer(
                name="TransferAddFileResponse",
                fields={
                    "transfer_id": serializers.UUIDField(),
                    "transfer_file_id": serializers.UUIDField(),
                    "upload_id": serializers.CharField(),
                    "s3_key": serializers.CharField(),
                    "chunk_size": serializers.IntegerField(),
                },
            )
        },
    )
    @action(detail=False, methods=["post"], url_path="add-file")
    def add_file(self, request):
        """Attach a file to a draft transfer.

        If the body carries a ``transfer_id``, the file lands on that
        existing draft (owned by the caller, not yet finalized). If the
        field is omitted, a new draft is created on the fly and the file
        is attached to it — no dedicated "create transfer" endpoint is
        needed. Either way the response shape is the same, with
        ``transfer_id`` echoed so subsequent calls can bind to the draft.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transfer_id = data.get("transfer_id")

        with transaction.atomic():
            if transfer_id is None:
                # First drop in a session — create the draft as a side-effect.
                # ``expires_at`` gets a placeholder; finalize overwrites it.
                # No cumulative guards needed: count=1 and total_size equals
                # the single file's size, which the serializer already bounded
                # by the per-file limit (≤ total limit by invariant).
                transfer = models.Transfer.objects.create(
                    owner=request.user,
                    expires_at=timezone.now()
                    + timedelta(
                        days=int(settings.TRANSFER_DEFAULT_EXPIRY_DAYS)
                    ),
                )
            else:
                try:
                    transfer = self.get_queryset().get(id=transfer_id)
                except models.Transfer.DoesNotExist as exc:
                    raise drf.exceptions.NotFound(
                        "Transfer not found."
                    ) from exc
                self._check_draft(transfer)

                # Cumulative guards against drip-feed bypass: the serializer
                # only sees one file at a time, so totals have to be recomputed
                # from whatever is already attached.
                aggregates = transfer.files.aggregate(
                    count=Count("pk"), total_size=Sum("size")
                )
                existing_count = aggregates["count"] or 0
                existing_total = aggregates["total_size"] or 0

                if existing_count >= settings.TRANSFER_MAX_FILES_PER_TRANSFER:
                    raise drf.exceptions.ValidationError(
                        {
                            "files": (
                                f"A transfer cannot contain more than "
                                f"{settings.TRANSFER_MAX_FILES_PER_TRANSFER} files."
                            )
                        }
                    )
                if existing_total + data["size"] > settings.TRANSFER_MAX_TOTAL_SIZE:
                    max_go = settings.TRANSFER_MAX_TOTAL_SIZE // (1024**3)
                    raise drf.exceptions.ValidationError(
                        {
                            "size": f"Total transfer size exceeds maximum of {max_go} Go."
                        }
                    )

            s3_key = f"transfers/{transfer.id}/{uuid.uuid4()}/{data['filename']}"
            upload_id = s3.create_multipart_upload(
                key=s3_key, content_type=data["mime_type"]
            )
            transfer_file = models.TransferFile.objects.create(
                transfer=transfer,
                filename=data["filename"],
                size=data["size"],
                mime_type=data["mime_type"],
                s3_key=s3_key,
                upload_id=upload_id,
            )
        return drf.response.Response(
            {
                "transfer_id": str(transfer.id),
                "transfer_file_id": str(transfer_file.id),
                "upload_id": upload_id,
                "s3_key": s3_key,
                "chunk_size": settings.TRANSFER_CHUNK_SIZE,
            },
            status=201,
        )

    @extend_schema(
        request=TransferRemoveFileSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="remove-file")
    def remove_file(self, request, pk=None):
        """Detach a single file from a draft transfer.

        Best-effort S3 cleanup: aborts any in-progress multipart, deletes any
        object already landed. Safe to call on a half-uploaded file.

        If the removed file was the last one on the draft, the Transfer
        itself is dropped too — a draft carries no metadata of its own, so
        an empty draft has no reason to linger. The server enforces this
        invariant so clients that don't go through our frontend can't leave
        headless drafts in the DB until the abandoned-upload cron picks
        them up at T+24h.
        """
        transfer = self.get_object()
        self._check_draft(transfer)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            transfer_file = transfer.files.get(
                id=serializer.validated_data["transfer_file_id"]
            )
        except models.TransferFile.DoesNotExist as exc:
            raise drf.exceptions.NotFound("Transfer file not found.") from exc

        if transfer_file.upload_id:
            s3.abort_multipart_upload(
                key=transfer_file.s3_key, upload_id=transfer_file.upload_id
            )
        s3.delete_object(transfer_file.s3_key)

        with transaction.atomic():
            transfer_file.delete()
            # Bypass the related manager's prefetch cache (populated by
            # ``get_queryset().prefetch_related("files")`` during
            # ``self.get_object()``) with a fresh query — otherwise we'd see
            # the stale list that still contains the row we just deleted.
            if not models.TransferFile.objects.filter(transfer=transfer).exists():
                transfer.delete()

        return drf.response.Response(status=204)

    @extend_schema(
        request=TransferFinalizeSerializer,
        responses={200: TransferDetailSerializer},
    )
    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        """Finalize a transfer once all its files have been uploaded.

        The request body carries the full metadata set — title, expires_in_days,
        sharing_mode, recipients, sensitive. This is the only point where
        metadata is written: during the draft phase the transfer holds
        placeholder defaults from ``create``, and every field is overwritten
        here before the transition.

        Generates the public token, sets ``upload_completed_at`` on the
        transfer, fires ``TRANSFER_CREATED``, and schedules recipient emails
        in email mode. Callers must have successfully called ``complete-upload``
        on every file first. Idempotent on an already-finalized transfer:
        returns the current state without applying the body.
        """
        transfer = self.get_object()

        if transfer.is_finalized:
            serializer = TransferDetailSerializer(transfer)
            return drf.response.Response(serializer.data)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metadata = serializer.validated_data

        files = list(transfer.files.all())
        if not files:
            raise drf.exceptions.ValidationError(
                {"files": "Transfer has no files to finalize."}
            )
        pending = [str(f.id) for f in files if f.upload_completed_at is None]
        if pending:
            raise drf.exceptions.ValidationError(
                {
                    "files": (
                        "Cannot finalize: some files have not completed "
                        "their upload yet."
                    ),
                    "pending_file_ids": pending,
                }
            )

        with transaction.atomic():
            transfer.title = metadata["title"]
            transfer.sensitive = metadata["sensitive"]
            transfer.sharing_mode = metadata["sharing_mode"]
            # Anchor the expiry clock at finalize time — the countdown makes
            # sense from the moment the link is published, not from whenever
            # the user happened to start the draft.
            transfer.expires_at = timezone.now() + timedelta(
                days=int(metadata["expires_in_days"])
            )
            transfer.public_token = _generate_public_token()
            transfer.upload_completed_at = timezone.now()
            transfer.save(
                update_fields=[
                    "title",
                    "sensitive",
                    "sharing_mode",
                    "expires_at",
                    "public_token",
                    "upload_completed_at",
                    "updated_at",
                ]
            )

            # Replace recipients wholesale: drafts start with none, callers may
            # have bounced between email and link modes locally, so the only
            # source of truth is what lands in this request body.
            transfer.recipients.all().delete()
            if metadata["sharing_mode"] == SharingMode.EMAIL:
                for email in metadata["recipients"]:
                    models.TransferRecipient.objects.create(
                        transfer=transfer, email=email,
                    )

            _log_event(transfer, TransferEventType.TRANSFER_CREATED, request)

            if transfer.sharing_mode == SharingMode.EMAIL:
                from core.tasks import send_recipient_invitations_task

                transaction.on_commit(
                    lambda: send_recipient_invitations_task.delay(str(transfer.id))
                )

        detail = TransferDetailSerializer(transfer)
        return drf.response.Response(detail.data)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["post"], url_path="abort-upload")
    def abort_upload(self, request, pk=None):
        """Abort the entire transfer, including all its files.

        All-or-nothing semantics: aborting any part of a not-yet-finalized
        transfer nukes the whole thing — all pending S3 multipart uploads
        are aborted, every ``TransferFile`` row is dropped, and the parent
        ``Transfer`` is deleted. Can only be called on a non-finalized
        transfer (use ``revoke`` to tear down a finalized one).
        """
        transfer = self.get_object()

        if transfer.is_finalized:
            raise drf.exceptions.ValidationError(
                {"status": "Transfer is already finalized; use revoke instead."}
            )

        transfer.abort_pending_uploads()
        transfer.delete()

        return drf.response.Response(status=204)

    @extend_schema(responses={200: TransferDetailSerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        """Revoke a transfer — marks it as revoked and deletes S3 files."""
        transfer = self.get_object()

        if transfer.status != TransferStatus.ACTIVE:
            raise drf.exceptions.ValidationError(
                {"status": "Only active transfers can be revoked."}
            )

        transfer.delete_s3_objects()

        transfer.status = TransferStatus.REVOKED
        transfer.revoked_at = timezone.now()
        transfer.save(update_fields=["status", "revoked_at", "updated_at"])

        _log_event(transfer, TransferEventType.TRANSFER_REVOKED, request)

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
