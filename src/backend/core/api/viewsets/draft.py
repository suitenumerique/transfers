"""API ViewSet for TransferDraft — the ephemeral upload session.

A draft holds files-in-transit (and nothing else — no metadata) from the
first drop until the user clicks "Create link". At that point the finalize
action creates a fresh ``Transfer`` with the request body's metadata and
reparents the draft's ``TransferFile`` rows to it, then deletes the draft.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

import botocore
import rest_framework as drf
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action

from core import models
from core.api.permissions import IsAuthenticated
from core.api.serializers import (
    DraftAddFileSerializer,
    DraftCompleteUploadSerializer,
    DraftDetailSerializer,
    DraftFinalizeSerializer,
    DraftRemoveFileSerializer,
    DraftSignPartSerializer,
    TransferDetailSerializer,
)
from core.api.utils import log_agent_event
from core.enums import SharingMode, TransferEventType
from core.services import s3
from core.tasks import import_drive_file_task


class TransferDraftViewSet(viewsets.GenericViewSet):
    """Endpoints for the draft lifecycle: add-file, sign-part, complete-upload,
    remove-file, abort, finalize. Nothing public — a draft never holds
    metadata, never surfaces in listings, and dies at abort or finalize.
    """

    permission_classes = [IsAuthenticated]
    queryset = models.TransferDraft.objects.all()

    def get_queryset(self):
        return models.TransferDraft.objects.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action == "add_file":
            return DraftAddFileSerializer
        if self.action == "sign_part":
            return DraftSignPartSerializer
        if self.action == "complete_upload":
            return DraftCompleteUploadSerializer
        if self.action == "remove_file":
            return DraftRemoveFileSerializer
        if self.action == "finalize":
            return DraftFinalizeSerializer
        if self.action == "retrieve":
            return DraftDetailSerializer
        return DraftAddFileSerializer

    def retrieve(self, request, pk=None):
        """GET /drafts/{id}/ — slim projection of the draft's file list with
        per-file states, used by the frontend to poll server-side imports
        (Drive) and observe ``importing → done`` transitions.
        """
        draft = self.get_object()
        return drf.response.Response(DraftDetailSerializer(draft).data)

    def _get_pending_file(self, draft, file_id):
        try:
            tf = draft.files.get(id=file_id)
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

    @extend_schema(
        request=DraftAddFileSerializer,
        responses={
            201: inline_serializer(
                name="DraftAddFileResponse",
                fields={
                    "draft_id": serializers.UUIDField(),
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
        """Attach a file to a draft.

        If the body carries a ``draft_id``, the file lands on that existing
        draft (owned by the caller). If the field is omitted, a new draft
        is created on the fly as a side-effect — there is no separate
        "create draft" endpoint. Either way the response echoes the
        ``draft_id`` so subsequent calls bind to the same draft.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        draft_id = data.get("draft_id")

        with transaction.atomic():
            if draft_id is None:
                # First drop of the session — open a fresh draft. No cumulative
                # guards: count=1 and total_size = this single file's size,
                # which the serializer already bounded to the per-file limit
                # (and per-file ≤ total by invariant).
                draft = models.TransferDraft.objects.create(owner=request.user)
            else:
                try:
                    draft = self.get_queryset().get(id=draft_id)
                except models.TransferDraft.DoesNotExist as exc:
                    raise drf.exceptions.NotFound("Draft not found.") from exc

                # Cumulative guards against drip-feed bypass: the serializer
                # only sees one file at a time, so totals are recomputed from
                # whatever is already attached to the draft.
                aggregates = draft.files.aggregate(
                    count=Count("pk"), total_size=Sum("size", default=0)
                )
                if aggregates["count"] >= settings.TRANSFER_MAX_FILES_PER_TRANSFER:
                    raise drf.exceptions.ValidationError(
                        {
                            "files": (
                                f"A transfer cannot contain more than "
                                f"{settings.TRANSFER_MAX_FILES_PER_TRANSFER} files."
                            )
                        }
                    )
                if (
                    aggregates["total_size"] + data["size"]
                    > settings.TRANSFER_MAX_TOTAL_SIZE
                ):
                    max_go = settings.TRANSFER_MAX_TOTAL_SIZE // (1024**3)
                    raise drf.exceptions.ValidationError(
                        {"size": f"Total transfer size exceeds maximum of {max_go} Go."}
                    )

            # Build the TransferFile in-memory first so ``tf.id`` (auto-set by
            # BaseModel's uuid.uuid4 default) is available for the S3 key.
            # The key stays valid across finalize-time reparenting because it
            # doesn't embed the draft/transfer id — only the file id.
            transfer_file = models.TransferFile(
                draft=draft,
                filename=data["filename"],
                size=data["size"],
                mime_type=data["mime_type"],
                source_url=data.get("source_url", ""),
            )
            transfer_file.s3_key = f"transfers/{transfer_file.id}/{data['filename']}"

            if transfer_file.source_url:
                # Drive import path: no multipart opened synchronously —
                # the celery task will open its own, drain Drive into it,
                # and set ``upload_completed_at`` when done. The client
                # doesn't need ``upload_id`` / ``chunk_size`` because it
                # won't be uploading any parts.
                transfer_file.save()
                transaction.on_commit(
                    lambda: import_drive_file_task.delay(str(transfer_file.id))
                )
            else:
                upload_id = s3.create_multipart_upload(
                    key=transfer_file.s3_key, content_type=data["mime_type"]
                )
                transfer_file.upload_id = upload_id
                transfer_file.save()

        response_body = {
            "draft_id": str(draft.id),
            "transfer_file_id": str(transfer_file.id),
        }
        if not transfer_file.source_url:
            response_body["upload_id"] = transfer_file.upload_id
            response_body["s3_key"] = transfer_file.s3_key
            response_body["chunk_size"] = settings.TRANSFER_CHUNK_SIZE
        return drf.response.Response(response_body, status=201)

    @extend_schema(
        request=DraftSignPartSerializer,
        responses={
            200: inline_serializer(
                name="DraftSignPartResponse",
                fields={
                    "url": serializers.URLField(),
                    "part_number": serializers.IntegerField(),
                },
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="sign-part")
    def sign_part(self, request, pk=None):
        """Return a presigned URL for one part of an in-progress upload."""
        draft = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        transfer_file = self._get_pending_file(draft, data["transfer_file_id"])
        url = s3.sign_upload_part(
            key=transfer_file.s3_key,
            upload_id=transfer_file.upload_id,
            part_number=data["part_number"],
        )
        return drf.response.Response({"url": url, "part_number": data["part_number"]})

    @extend_schema(
        request=DraftCompleteUploadSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="complete-upload")
    def complete_upload(self, request, pk=None):
        """Close the S3 multipart upload for a single file.

        Per-file verb: the draft as a whole is not yet finalize-ready until
        every one of its files has landed here. If S3 rejects the completion
        (wrong ETag, missing part…), the draft is unrecoverable — we
        best-effort abort all in-progress multipart uploads and nuke the
        draft (matches the all-or-nothing semantics of the old abort-upload).
        """
        draft = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        transfer_file = self._get_pending_file(draft, data["transfer_file_id"])

        try:
            s3.complete_multipart_upload(
                key=transfer_file.s3_key,
                upload_id=transfer_file.upload_id,
                parts=data["parts"],
            )
        except botocore.exceptions.ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            s3.abort_uploads_for_files(draft.files.all())
            draft.delete()
            raise drf.exceptions.ValidationError(
                {
                    "parts": (
                        f"S3 rejected the multipart upload completion "
                        f"({error_code}). The draft has been aborted, "
                        f"please restart it from scratch."
                    )
                }
            ) from exc

        # Verify landed-size matches the declared one. See viewsets/transfer.py
        # history for the rationale; same guard applies here.
        actual_size = s3.head_object_size(transfer_file.s3_key)
        if actual_size != transfer_file.size:
            files = list(draft.files.all())
            s3.abort_uploads_for_files(files)
            s3.delete_objects_for_files(files)
            draft.delete()
            raise drf.exceptions.ValidationError(
                {
                    "parts": (
                        f"Uploaded file size ({actual_size} bytes) does not "
                        f"match the declared size ({transfer_file.size} "
                        f"bytes). The draft has been aborted."
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
        request=DraftRemoveFileSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="remove-file")
    def remove_file(self, request, pk=None):
        """Detach a file from a draft.

        Best-effort S3 cleanup (abort multipart, delete object). If it was
        the last file, the draft itself is deleted — empty drafts have no
        reason to exist.
        """
        draft = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            transfer_file = draft.files.get(
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
            # Fresh query bypasses any prefetched-cache staleness from
            # get_object() (which was unlikely here but cheap to guarantee).
            if not models.TransferFile.objects.filter(draft=draft).exists():
                draft.delete()

        return drf.response.Response(status=204)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["post"])
    def abort(self, request, pk=None):
        """Drop a draft wholesale — aborts every in-progress S3 multipart,
        deletes every object already landed, deletes the draft + its files
        via cascade. All-or-nothing; safe to call on a half-uploaded draft.
        """
        draft = self.get_object()
        files = list(draft.files.all())
        s3.abort_uploads_for_files(files)
        s3.delete_objects_for_files(files)
        draft.delete()
        return drf.response.Response(status=204)

    @extend_schema(
        request=DraftFinalizeSerializer,
        responses={200: TransferDetailSerializer},
    )
    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        """Create the Transfer and reparent the draft's files to it.

        Single write-point for transfer-level metadata: the body carries
        ``title`` / ``sharing_mode`` / ``recipients`` / ``expires_in_days``.
        The Transfer is born fully-formed (public_token
        populated, ``created_at`` acts as the publication timestamp), every
        TransferFile in the draft is reparented in one UPDATE, and the draft
        is deleted. Recipient emails are scheduled on transaction commit.

        Refuses to finalize a draft whose files haven't all completed their
        multipart upload (``upload_completed_at IS NULL`` on a per-file basis).
        """
        draft = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metadata = serializer.validated_data

        files = list(draft.files.all())
        if not files:
            raise drf.exceptions.ValidationError(
                {"files": "Draft has no files to finalize."}
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
            transfer = models.Transfer.objects.create(
                owner=draft.owner,
                title=metadata["title"],
                sharing_mode=metadata["sharing_mode"],
                expires_at=timezone.now()
                + timedelta(days=int(metadata["expires_in_days"])),
            )
            models.TransferFile.objects.filter(draft=draft).update(
                transfer=transfer, draft=None
            )
            if metadata["sharing_mode"] == SharingMode.EMAIL:
                for email in metadata["recipients"]:
                    models.TransferRecipient.objects.create(
                        transfer=transfer,
                        email=email,
                    )

            log_agent_event(transfer, TransferEventType.TRANSFER_CREATED, request)

            if transfer.sharing_mode == SharingMode.EMAIL:
                from core.tasks import send_recipient_invitations_task

                transaction.on_commit(
                    lambda: send_recipient_invitations_task.delay(str(transfer.id))
                )

            draft.delete()

        detail = TransferDetailSerializer(transfer)
        return drf.response.Response(detail.data)


# --- Helpers ---
