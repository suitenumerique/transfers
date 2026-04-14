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
    TransferAbortUploadSerializer,
    TransferCompleteUploadSerializer,
    TransferCreateSerializer,
    TransferDetailSerializer,
    TransferEventSerializer,
    TransferListSerializer,
    TransferSignPartSerializer,
)
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
        if self.action == "abort_upload":
            return TransferAbortUploadSerializer
        return TransferDetailSerializer

    def get_queryset(self):
        queryset = (
            models.Transfer.objects.filter(owner=self.request.user)
            .prefetch_related("files")
            .order_by("-created_at")
        )
        if self.action == "list":
            # Hide transfers whose upload is not yet completed.
            queryset = queryset.filter(
                files__upload_completed_at__isnull=False
            ).distinct()
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
                name="TransferInitiateResponse",
                fields={
                    "transfer_id": serializers.UUIDField(),
                    "transfer_file_id": serializers.UUIDField(),
                    "upload_id": serializers.CharField(),
                    "s3_key": serializers.CharField(),
                    "chunk_size": serializers.IntegerField(),
                    "public_token": serializers.CharField(),
                },
            )
        },
    )
    def create(self, request, *args, **kwargs):
        """Initiate a new transfer + multipart upload.

        Creates the ``Transfer`` and ``TransferFile`` rows, then calls
        ``create_multipart_upload`` on S3 and returns the ``upload_id`` for the
        browser to use with subsequent ``sign_part`` / ``complete_upload``
        calls.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        expires_in_days = serializer.get_expires_in_days(data)

        password = data.get("password") or ""
        password_hash = make_password(password) if password else ""

        with transaction.atomic():
            transfer = models.Transfer.objects.create(
                owner=request.user,
                title=data.get("title") or "",
                sensitive=data.get("sensitive", False),
                password_hash=password_hash,
                expires_at=timezone.now() + timedelta(days=expires_in_days),
            )

            s3_key = f"transfers/{transfer.id}/{uuid.uuid4()}/{data['filename']}"
            upload_id = s3.create_multipart_upload(
                key=s3_key, content_type=data.get("mime_type") or ""
            )

            transfer_file = models.TransferFile.objects.create(
                transfer=transfer,
                filename=data["filename"],
                size=data["size"],
                mime_type=data.get("mime_type") or "",
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
                "public_token": transfer.public_token,
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
        responses={200: TransferDetailSerializer},
    )
    @action(detail=True, methods=["post"], url_path="complete-upload")
    def complete_upload(self, request, pk=None):
        """Complete a multipart upload and finalize the transfer.

        S3 is the authority for the (PartNumber, ETag) list — DRF only
        validates the shape of the payload, S3 validates the content. If S3
        rejects the completion (wrong ETag, missing part, invalid order…),
        the multipart is unrecoverable, so we best-effort abort it on S3 and
        delete the half-baked DB rows, then return 400 to the client.
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
            # S3 rejected the completion — clean up and report a 400.
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            s3.abort_multipart_upload(
                key=transfer_file.s3_key, upload_id=transfer_file.upload_id
            )
            with transaction.atomic():
                transfer_file.delete()
                has_other_files = models.TransferFile.objects.filter(
                    transfer=transfer
                ).exists()
                if not has_other_files:
                    transfer.delete()
            raise drf.exceptions.ValidationError(
                {
                    "parts": (
                        f"S3 rejected the multipart upload completion "
                        f"({error_code}). The upload has been aborted, "
                        f"please restart the transfer."
                    )
                }
            ) from exc

        with transaction.atomic():
            transfer_file.upload_completed_at = timezone.now()
            transfer_file.upload_id = ""
            transfer_file.save(
                update_fields=["upload_completed_at", "upload_id", "updated_at"]
            )
            _log_event(transfer, TransferEventType.TRANSFER_CREATED, request)

        detail_serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(detail_serializer.data)

    @extend_schema(
        request=TransferAbortUploadSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="abort-upload")
    def abort_upload(self, request, pk=None):
        """Abort an in-progress multipart upload.

        Deletes the ``TransferFile`` row and, if no other files remain, the
        parent ``Transfer`` too. Safe to call even if the upload never really
        started on S3.
        """
        transfer = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            transfer_file = transfer.files.get(id=data["transfer_file_id"])
        except models.TransferFile.DoesNotExist as exc:
            raise drf.exceptions.NotFound("Transfer file not found.") from exc

        if transfer_file.upload_id:
            s3.abort_multipart_upload(
                key=transfer_file.s3_key, upload_id=transfer_file.upload_id
            )

        with transaction.atomic():
            transfer_file.delete()
            # Query the model class directly instead of `transfer.files` —
            # the prefetch cache from get_object() would still show the
            # just-deleted row otherwise.
            has_other_files = models.TransferFile.objects.filter(
                transfer=transfer
            ).exists()
            if not has_other_files:
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
