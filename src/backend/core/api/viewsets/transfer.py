"""API ViewSet for Transfer model (authenticated agent endpoints)."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import boto3
import rest_framework as drf
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser

from core import models
from core.api.permissions import IsAuthenticated
from core.api.serializers import (
    TransferCreateSerializer,
    TransferDetailSerializer,
    TransferEventSerializer,
    TransferListSerializer,
)
from core.api.viewsets import Pagination
from core.enums import ActorType, TransferEventType, TransferStatus


def _get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", None) or "us-east-1",
    )


def _delete_transfer_files_from_s3(transfer):
    """Delete all S3 objects for a transfer."""
    s3 = _get_s3_client()
    bucket = settings.TRANSFERS_BUCKET_NAME
    for tf in transfer.files.all():
        try:
            s3.delete_object(Bucket=bucket, Key=tf.s3_key)
        except Exception:  # noqa: S110
            pass


class TransferViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """ViewSet for managing transfers (authenticated agent)."""

    permission_classes = [IsAuthenticated]
    pagination_class = Pagination
    parser_classes = [MultiPartParser, drf.parsers.JSONParser]

    def get_serializer_class(self):
        if self.action == "create":
            return TransferCreateSerializer
        if self.action == "list":
            return TransferListSerializer
        if self.action == "events":
            return TransferEventSerializer
        return TransferDetailSerializer

    def get_queryset(self):
        return (
            models.Transfer.objects.filter(owner=self.request.user)
            .prefetch_related("files", "recipients")
            .order_by("-created_at")
        )

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "password": {"type": "string"},
                    "expires_in_days": {"type": "integer"},
                    "recipients": {
                        "type": "array",
                        "items": {"type": "string", "format": "email"},
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string", "format": "binary"},
                    },
                },
                "required": ["recipients", "files"],
            }
        },
        responses={201: TransferDetailSerializer},
    )
    def create(self, request, *args, **kwargs):
        """Create a new transfer with files and recipients."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        files = request.FILES.getlist("files")
        if not files:
            raise drf.exceptions.ValidationError({"files": "At least one file is required."})

        expires_in_days = serializer.get_expires_in_days(data)

        with transaction.atomic():
            transfer = models.Transfer.objects.create(
                owner=request.user,
                title=data.get("title", ""),
                message=data.get("message", ""),
                expires_at=timezone.now() + timedelta(days=expires_in_days),
            )

            if data.get("password"):
                transfer.set_password(data["password"])
                transfer.save(update_fields=["password_hash"])

            # Upload files to S3
            s3 = _get_s3_client()
            bucket = settings.TRANSFERS_BUCKET_NAME
            for uploaded_file in files:
                s3_key = f"transfers/{transfer.id}/{uuid.uuid4()}/{uploaded_file.name}"
                s3.upload_fileobj(uploaded_file, bucket, s3_key)
                models.TransferFile.objects.create(
                    transfer=transfer,
                    filename=uploaded_file.name,
                    size=uploaded_file.size,
                    mime_type=uploaded_file.content_type or "",
                    s3_key=s3_key,
                )

            # Create recipients
            for email in data["recipients"]:
                models.TransferRecipient.objects.create(
                    transfer=transfer,
                    email=email,
                )

            # Log event
            models.TransferEvent.objects.create(
                transfer_id=transfer.id,
                event_type=TransferEventType.TRANSFER_CREATED,
                actor_type=ActorType.AGENT,
                actor_id=request.user.id,
                ip=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

        # TODO: send notification emails to recipients

        detail_serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(detail_serializer.data, status=201)

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

        models.TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.TRANSFER_REVOKED,
            actor_type=ActorType.AGENT,
            actor_id=request.user.id,
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        serializer = TransferDetailSerializer(transfer)
        return drf.response.Response(serializer.data)

    @extend_schema(responses={200: TransferEventSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        """List events for a transfer."""
        transfer = self.get_object()
        events = models.TransferEvent.objects.filter(
            transfer_id=transfer.id
        ).order_by("-created_at")
        page = self.paginate_queryset(events)
        if page is not None:
            serializer = TransferEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = TransferEventSerializer(events, many=True)
        return drf.response.Response(serializer.data)
