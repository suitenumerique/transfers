"""API views for the download page (no authentication required)."""

from django.conf import settings
from django.http import StreamingHttpResponse

import rest_framework as drf
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from core import models
from core.api.serializers import DownloadTransferSerializer
from core.api.viewsets.transfer import _get_s3_client
from core.enums import ActorType, TransferEventType, TransferStatus
from core.tasks import send_file_downloaded_notification, send_link_opened_notification


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


def _log_event(transfer, event_type, request, payload=None):
    models.TransferEvent.objects.create(
        transfer_id=transfer.id,
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
        send_link_opened_notification.delay(str(transfer.id))
        serializer = DownloadTransferSerializer(transfer)
        return drf.response.Response(serializer.data)


class DownloadFileView(APIView):
    """Download a single file from a transfer."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, public_token, file_id):
        transfer = _get_transfer_or_404(public_token)
        _check_accessible(transfer)

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
        send_file_downloaded_notification.delay(str(transfer.id), transfer_file.filename)

        response = StreamingHttpResponse(
            s3_response["Body"].iter_chunks(),
            content_type=transfer_file.mime_type or "application/octet-stream",
        )
        response["Content-Disposition"] = f'attachment; filename="{transfer_file.filename}"'
        response["Content-Length"] = transfer_file.size
        return response
