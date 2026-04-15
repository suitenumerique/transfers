"""API ViewSet for Transfer model (authenticated agent endpoints)."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

import botocore
import rest_framework as drf
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action

from core import models
from core.api.permissions import IsAuthenticated
from core.api.serializers import (
    TransferCompleteUploadSerializer,
    TransferCreateSerializer,
    TransferDetailSerializer,
    TransferEventSerializer,
    TransferListSerializer,
    TransferSignPartSerializer,
)
from core.models import _generate_public_token
from core.api.viewsets import Pagination
from core.enums import ActorType, TransferEventType, TransferStatus
from core.services import s3


def _delete_transfer_files_from_s3(transfer):
    """Delete all S3 objects for a transfer."""
    for tf in transfer.files.all():
        if tf.s3_key:
            s3.delete_object(tf.s3_key)


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
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """ViewSet for managing transfers (authenticated agent)."""

    permission_classes = [IsAuthenticated]
    pagination_class = Pagination

    def get_serializer_class(self):
        if self.action == "create":
            return TransferCreateSerializer
        if self.action == "list":
            return TransferListSerializer
        if self.action == "events":
            return TransferEventSerializer
        if self.action == "sign_part":
            return TransferSignPartSerializer
        if self.action == "complete_upload":
            return TransferCompleteUploadSerializer
        return TransferDetailSerializer

    def get_queryset(self):
        queryset = (
            models.Transfer.objects.filter(owner=self.request.user)
            .prefetch_related("files")
            .order_by("-created_at")
        )
        if self.action == "list":
            # Hide transfers whose upload is not yet finalized.
            queryset = queryset.filter(upload_completed_at__isnull=False)
        return queryset

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

    @extend_schema(
        request=TransferCreateSerializer,
        responses={
            201: inline_serializer(
                name="TransferCreateResponse",
                fields={
                    "transfer_id": serializers.UUIDField(),
                    "chunk_size": serializers.IntegerField(),
                    "files": inline_serializer(
                        name="TransferCreateResponseFile",
                        fields={
                            "transfer_file_id": serializers.UUIDField(),
                            "upload_id": serializers.CharField(),
                            "s3_key": serializers.CharField(),
                        },
                        many=True,
                    ),
                },
            )
        },
    )
    def create(self, request, *args, **kwargs):
        """Create a transfer and initiate multipart uploads for all its files.

        The request body contains the transfer-level metadata plus the list
        of files. The response returns the transfer descriptor plus one
        upload descriptor per file, in the same order as the request.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        password = data.get("password") or ""
        password_hash = make_password(password) if password else ""

        with transaction.atomic():
            transfer = models.Transfer.objects.create(
                owner=request.user,
                title=data.get("title") or "",
                sensitive=data.get("sensitive", False),
                password_hash=password_hash,
                expires_at=timezone.now()
                + timedelta(days=int(data["expires_in_days"])),
            )

            file_descriptors = []
            for file_data in data["files"]:
                s3_key = (
                    f"transfers/{transfer.id}/{uuid.uuid4()}/{file_data['filename']}"
                )
                upload_id = s3.create_multipart_upload(
                    key=s3_key, content_type=file_data.get("mime_type") or ""
                )
                transfer_file = models.TransferFile.objects.create(
                    transfer=transfer,
                    filename=file_data["filename"],
                    size=file_data["size"],
                    mime_type=file_data.get("mime_type") or "",
                    s3_key=s3_key,
                    upload_id=upload_id,
                )
                file_descriptors.append(
                    {
                        "transfer_file_id": str(transfer_file.id),
                        "upload_id": upload_id,
                        "s3_key": s3_key,
                    }
                )

        return drf.response.Response(
            {
                "transfer_id": str(transfer.id),
                "chunk_size": settings.TRANSFER_CHUNK_SIZE,
                "files": file_descriptors,
            },
            status=201,
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
            for tf in transfer.files.all():
                if tf.upload_id:
                    try:
                        s3.abort_multipart_upload(
                            key=tf.s3_key, upload_id=tf.upload_id
                        )
                    except botocore.exceptions.ClientError:
                        pass
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
            for tf in transfer.files.all():
                if tf.upload_id:
                    try:
                        s3.abort_multipart_upload(
                            key=tf.s3_key, upload_id=tf.upload_id
                        )
                    except botocore.exceptions.ClientError:
                        pass
                s3.delete_object(tf.s3_key)
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
        request=None,
        responses={200: TransferDetailSerializer},
    )
    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        """Finalize a transfer once all its files have been uploaded.

        This is the transition that actually makes the transfer usable:
        generates the public token, sets ``upload_completed_at`` on the
        transfer, and fires the ``TRANSFER_CREATED`` event. Callers must
        have successfully called ``complete-upload`` on every file first.
        Idempotent: calling it twice on a finalized transfer just returns
        the current state without any side effect.
        """
        transfer = self.get_object()

        if transfer.is_finalized:
            serializer = TransferDetailSerializer(transfer)
            return drf.response.Response(serializer.data)

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
            transfer.public_token = _generate_public_token()
            transfer.upload_completed_at = timezone.now()
            transfer.save(
                update_fields=[
                    "public_token",
                    "upload_completed_at",
                    "updated_at",
                ]
            )
            _log_event(transfer, TransferEventType.TRANSFER_CREATED, request)

        serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(serializer.data)

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

        for tf in transfer.files.all():
            if tf.upload_id:
                try:
                    s3.abort_multipart_upload(
                        key=tf.s3_key, upload_id=tf.upload_id
                    )
                except botocore.exceptions.ClientError:
                    pass
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

        _delete_transfer_files_from_s3(transfer)

        transfer.status = TransferStatus.REVOKED
        transfer.revoked_at = timezone.now()
        transfer.save(update_fields=["status", "revoked_at", "updated_at"])

        _log_event(transfer, TransferEventType.TRANSFER_REVOKED, request)

        serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(serializer.data)

    @extend_schema(responses={200: TransferDetailSerializer})
    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        """Reactivate an expired transfer — same public_token, new expiry."""
        transfer = self.get_object()

        if transfer.status != TransferStatus.EXPIRED:
            raise drf.exceptions.ValidationError(
                {"status": "Only expired transfers can be reactivated."}
            )

        if transfer.files_deleted:
            raise drf.exceptions.ValidationError(
                {
                    "status": "Files have been permanently deleted; "
                    "this transfer cannot be reactivated."
                }
            )

        transfer.status = TransferStatus.ACTIVE
        transfer.expires_at = timezone.now() + timedelta(
            days=settings.TRANSFER_DEFAULT_EXPIRY_DAYS
        )
        transfer.revoked_at = None
        transfer.save(
            update_fields=["status", "expires_at", "revoked_at", "updated_at"]
        )

        _log_event(transfer, TransferEventType.TRANSFER_REACTIVATED, request)

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
