"""API views for the download page.

Permission is ``AllowAny`` (visitors don't need an account) but the global
authentication classes still run so that an authenticated agent visiting
their own transfer is recognised — those self-views are skipped from the
recipient activity log.
"""

from django.db import transaction
from django.http import HttpResponseRedirect

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api.serializers import DownloadTransferSerializer
from core.enums import (
    ActorType,
    DeactivationReason,
    ScanStatus,
    TransferEventType,
    TransferStatus,
)
from core.services.s3 import sign_download_url

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
    if transfer.status == TransferStatus.ACTIVE:
        # Edge case: deadline just passed but
        # ``deactivate_expired_transfers_task`` hasn't flipped the row
        # yet. Still surface "expired" so the recipient gets an accurate
        # error.
        if transfer.is_expired:
            return Response(
                {"detail": "This transfer has expired.", "reason": "expired"},
                status=410,
            )
        return None

    # Terminal or transitional state — what the visitor sees depends on
    # why we deactivated the transfer, not on whether the S3 purge has
    # run.
    if transfer.deactivation_reason == DeactivationReason.EXPIRED:
        return Response(
            {"detail": "This transfer has expired.", "reason": "expired"},
            status=410,
        )
    return Response(
        {
            "detail": "This transfer has been deactivated.",
            "reason": "deactivated",
        },
        status=403,
    )


def _record_visitor_event(transfer, event_type, request, payload=None):
    # Skip the event when an authenticated agent is visiting/downloading
    # their own transfer — recipient activity is the audit signal here,
    # owner self-checks aren't.
    if (
        request.user.is_authenticated
        and request.user.id == transfer.owner_id
    ):
        return
    models.TransferEvent.objects.create(
        transfer_id=transfer.id,
        event_type=event_type,
        actor_type=ActorType.EXTERNAL,
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        payload=payload or {},
    )


def _all_files_downloaded_once(transfer) -> bool:
    """True iff every file on this transfer has at least one FILE_DOWNLOADED event."""
    file_count = transfer.files.count()
    if not file_count:
        return False
    downloaded_count = (
        models.TransferEvent.objects.filter(
            transfer_id=transfer.id,
            event_type=TransferEventType.FILE_DOWNLOADED,
            # We count distinct file_ids and compare that to the number of
            # files. Events whose payload has no file_id (legacy rows from
            # before we stored it) all collapse to a single NULL, which COUNT
            # DISTINCT treats as one more "file" — pushing the total over the
            # threshold and deactivating the link before every file has
            # actually been downloaded. Excluding them keeps the count honest.
            payload__file_id__isnull=False,
        )
        .values("payload__file_id")
        .distinct()
        .count()
    )
    return downloaded_count >= file_count


class DownloadTransferView(APIView):
    """Get transfer info for the download page."""

    permission_classes = [AllowAny]

    def get(self, request, public_token):
        transfer = _fetch_transfer_by_token(public_token)
        if transfer is None:
            return Response(TRANSFER_NOT_FOUND_BODY, status=404)

        denied = _denied_access_response(transfer)
        if denied is not None:
            return denied

        _record_visitor_event(transfer, TransferEventType.LINK_OPENED, request)
        serializer = DownloadTransferSerializer(
            transfer, context={"request": request}
        )
        return Response(serializer.data)


class DownloadFileView(APIView):
    """Download a single file from a transfer."""

    permission_classes = [AllowAny]

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

        # Antivirus gate — fail closed. The file is only released once the
        # scanner has reported it CLEAN; anything else (still scanning,
        # infected, scan errored) blocks the download.
        if transfer_file.scan_status == ScanStatus.PENDING:
            return Response(
                {
                    "detail": "This file is still being scanned for viruses.",
                    "reason": "scan_pending",
                },
                status=202,
            )
        if transfer_file.scan_status not in (ScanStatus.CLEAN, ScanStatus.SKIPPED):
            return Response(
                {
                    "detail": "This file was blocked by the antivirus scan.",
                    "reason": "scan_blocked",
                },
                status=403,
            )

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

        # Auto-archive check: if this transfer was flagged as one-shot and
        # every file has now been downloaded at least once, deactivate the
        # link immediately (status → PENDING_FILE_DELETION) and schedule
        # the S3 purge for later via ``pending_deletion_at``. The periodic
        # ``delete_pending_transfer_files_task`` is what actually deletes
        # the bytes once that deadline has passed — long enough for the
        # in-flight GET we're about to redirect to to finish, even on a
        # 20 GiB file and a slow connection.
        #
        # Caveat — this is "first *access*", not "first completed download".
        # FILE_DOWNLOADED is recorded the moment we hand out the presigned
        # URL, before the S3 bytes are streamed: a link-preview bot, mail/AV
        # prefetcher, crawler or an open-then-cancel can therefore trip the
        # deactivation before the real recipient saves the file. We accept
        # that tradeoff because the feature is strictly opt-in
        # (``auto_archive_on_download``, default False) and the grace window
        # keeps the bytes around for the actual download to finish. Tying
        # deactivation to genuine completion would require S3 access logs /
        # bucket notifications, which is out of scope here.
        #
        # select_for_update serialises concurrent last-file downloads so
        # only one caller wins the ACTIVE→PENDING_FILE_DELETION transition
        # and emits the audit event. deactivate() is a conditional QuerySet
        # update that returns False when another worker already moved the
        # row — the event is skipped in that case.
        if transfer.auto_archive_on_download and transfer.status == TransferStatus.ACTIVE:
            with transaction.atomic():
                locked = models.Transfer.objects.select_for_update().get(pk=transfer.pk)
                if locked.status == TransferStatus.ACTIVE and _all_files_downloaded_once(locked):
                    if locked.deactivate(DeactivationReason.FIRST_DOWNLOAD):
                        models.TransferEvent.objects.create(
                            transfer_id=transfer.id,
                            event_type=TransferEventType.TRANSFER_DEACTIVATED_AFTER_FIRST_DOWNLOAD,
                            actor_type=ActorType.AGENT,
                        )

        # Redirect the browser straight to S3 so the download bytes never
        # transit through a Django worker. The presigned URL's short expiry
        # limits the shelf life of the URL if it leaks (browser history,
        # logs, copy-paste).
        return HttpResponseRedirect(url)
