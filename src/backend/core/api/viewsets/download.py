"""API views for the download page (no authentication required)."""

import io
import zipfile

from django.conf import settings
from django.http import StreamingHttpResponse

import rest_framework as drf
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from core import models
from core.api.serializers import (
    DownloadTransferLockedSerializer,
    DownloadTransferSerializer,
    VerifyPasswordSerializer,
)
from core.api.viewsets.transfer import _get_s3_client
from core.enums import ActorType, TransferEventType, TransferStatus


def _get_transfer_or_404(public_token: str) -> models.Transfer:
    try:
        return models.Transfer.objects.prefetch_related("files").get(
            public_token=public_token
        )
    except models.Transfer.DoesNotExist as err:
        raise drf.exceptions.NotFound("Transfer not found.") from err


def _check_accessible(transfer: models.Transfer) -> None:
    if transfer.status == TransferStatus.REVOKED:
        raise drf.exceptions.PermissionDenied("This transfer has been revoked.")
    if transfer.is_expired:
        raise drf.exceptions.PermissionDenied("This transfer has expired.")


def _require_password_for_download(transfer, request):
    if transfer.has_password:
        pwd = request.query_params.get("password", "")
        if not transfer.check_password(pwd):
            raise drf.exceptions.PermissionDenied("Invalid password.")


def _log_event(transfer, event_type, request, recipient_id=None, payload=None):
    models.TransferEvent.objects.create(
        transfer_id=transfer.id,
        recipient_id=recipient_id,
        event_type=event_type,
        actor_type=ActorType.EXTERNAL,
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        payload=payload or {},
    )


class DownloadTransferView(APIView):
    """Get transfer info for the download page."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, public_token):
        transfer = _get_transfer_or_404(public_token)
        _check_accessible(transfer)
        _log_event(transfer, TransferEventType.LINK_OPENED, request)

        if transfer.has_password:
            serializer = DownloadTransferLockedSerializer(transfer)
        else:
            serializer = DownloadTransferSerializer(transfer)
        return drf.response.Response(serializer.data)


class DownloadVerifyPasswordView(APIView):
    """Verify the transfer password."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=VerifyPasswordSerializer,
        responses={200: DownloadTransferSerializer, 403: None},
    )
    def post(self, request, public_token):
        transfer = _get_transfer_or_404(public_token)
        _check_accessible(transfer)

        serializer = VerifyPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        valid = transfer.check_password(serializer.validated_data["password"])
        _log_event(
            transfer,
            TransferEventType.PASSWORD_ATTEMPT,
            request,
            payload={"success": valid},
        )

        if not valid:
            raise drf.exceptions.PermissionDenied("Invalid password.")

        return drf.response.Response(DownloadTransferSerializer(transfer).data)


class DownloadFileView(APIView):
    """Download a single file from a transfer."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, public_token, file_id):
        transfer = _get_transfer_or_404(public_token)
        _check_accessible(transfer)
        _require_password_for_download(transfer, request)

        try:
            transfer_file = transfer.files.get(id=file_id)
        except models.TransferFile.DoesNotExist as err:
            raise drf.exceptions.NotFound("File not found.") from err

        s3 = _get_s3_client()
        bucket = settings.TRANSFERS_BUCKET_NAME
        s3_response = s3.get_object(Bucket=bucket, Key=transfer_file.s3_key)

        _log_event(
            transfer,
            TransferEventType.FILE_DOWNLOADED,
            request,
            payload={"file_id": str(transfer_file.id), "filename": transfer_file.filename},
        )

        response = StreamingHttpResponse(
            s3_response["Body"].iter_chunks(),
            content_type=transfer_file.mime_type or "application/octet-stream",
        )
        response["Content-Disposition"] = f'attachment; filename="{transfer_file.filename}"'
        response["Content-Length"] = transfer_file.size
        return response


class DownloadAllView(APIView):
    """Download all files from a transfer as a zip archive."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, public_token):
        transfer = _get_transfer_or_404(public_token)
        _check_accessible(transfer)
        _require_password_for_download(transfer, request)

        files = transfer.files.all()
        if not files:
            raise drf.exceptions.NotFound("No files in this transfer.")

        s3 = _get_s3_client()
        bucket = settings.TRANSFERS_BUCKET_NAME

        # Build zip in memory (acceptable for MVP, revisit for large transfers)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for tf in files:
                s3_response = s3.get_object(Bucket=bucket, Key=tf.s3_key)
                zf.writestr(tf.filename, s3_response["Body"].read())

        zip_buffer.seek(0)

        _log_event(
            transfer,
            TransferEventType.ALL_FILES_DOWNLOADED,
            request,
        )

        zip_name = f"{transfer.title or 'transfert'}.zip"
        response = StreamingHttpResponse(
            zip_buffer,
            content_type="application/zip",
        )
        response["Content-Disposition"] = f'attachment; filename="{zip_name}"'
        response["Content-Length"] = zip_buffer.getbuffer().nbytes
        return response
