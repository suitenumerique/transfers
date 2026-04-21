"""API views for the download page (no authentication required)."""

from django.http import HttpResponseRedirect

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api.serializers import DownloadTransferSerializer
from core.enums import ActorType, TransferEventType, TransferStatus
from core.services.s3 import sign_download_url
from core.tasks import send_file_downloaded_notification, send_link_opened_notification

TRANSFER_NOT_FOUND_BODY = {"detail": "Transfer not found.", "reason": "not_found"}


def _fetch_transfer_by_token(public_token: str) -> models.Transfer | None:
    try:
        return models.Transfer.objects.prefetch_related("files").get(
            public_token=public_token
        )
    except models.Transfer.DoesNotExist:
        return None


def _denied_access_response(transfer: models.Transfer) -> Response | None:
    """Return an error Response if the public visitor cannot access the transfer,
    or None if access is allowed.
    """
    if transfer.status == TransferStatus.REVOKED:
        return Response(
            {"detail": "This transfer has been revoked.", "reason": "revoked"},
            status=403,
        )
    if transfer.is_expired:
        return Response(
            {"detail": "This transfer has expired.", "reason": "expired"},
            status=410,
        )
    return None


def _record_visitor_event(transfer, event_type, request, payload=None):
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
        transfer = _fetch_transfer_by_token(public_token)
        if transfer is None:
            return Response(TRANSFER_NOT_FOUND_BODY, status=404)

        denied = _denied_access_response(transfer)
        if denied is not None:
            return denied

        _record_visitor_event(transfer, TransferEventType.LINK_OPENED, request)
        send_link_opened_notification.delay(str(transfer.id))
        serializer = DownloadTransferSerializer(transfer)
        return Response(serializer.data)


class DownloadFileView(APIView):
    """Download a single file from a transfer."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, public_token, file_id):
        transfer = _fetch_transfer_by_token(public_token)
        if transfer is None:
            return Response(TRANSFER_NOT_FOUND_BODY, status=404)

        denied = _denied_access_response(transfer)
        if denied is not None:
            return denied

        try:
            transfer_file = transfer.files.get(
                id=file_id, upload_completed_at__isnull=False
            )
        except models.TransferFile.DoesNotExist:
            return Response(TRANSFER_NOT_FOUND_BODY, status=404)

        url = sign_download_url(
            transfer_file.s3_key,
            transfer_file.filename,
            transfer_file.mime_type,
        )

        _record_visitor_event(
            transfer,
            TransferEventType.FILE_DOWNLOADED,
            request,
            payload={
                "file_id": str(transfer_file.id),
                "filename": transfer_file.filename,
            },
        )
        send_file_downloaded_notification.delay(
            str(transfer.id), transfer_file.filename
        )

        # Redirect the browser straight to S3 so the download bytes never
        # transit through a Django worker. The presigned URL's short expiry
        # limits the shelf life of the URL if it leaks (browser history,
        # logs, copy-paste).
        return HttpResponseRedirect(url)
