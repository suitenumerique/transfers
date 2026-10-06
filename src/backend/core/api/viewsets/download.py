"""API views for the download page.

Permission is ``AllowAny`` (visitors don't need an account) but the global
authentication classes still run so that an authenticated agent visiting
their own transfer is recognised — those self-views are skipped from the
recipient activity log.
"""

from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone

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
from core.services.recipient_activity import files_downloaded_by
from core.services.s3 import sign_download_url

TRANSFER_NOT_FOUND_BODY = {"detail": "Transfer not found.", "reason": "not_found"}

# Per-purpose namespace for the signature (Django's ``salt``, not a secret:
# the secret is SECRET_KEY). Keeps a token signed for another use from
# being accepted here.
RESUME_SIGNATURE_NAMESPACE = "transfer-download-resume"


def _resume_token(transfer, file_id) -> str:
    """Capability handed out with a download URL: proves its holder already
    obtained this file, so it may fetch it again to finish an interrupted
    download — including on a one-shot transfer, during the grace window
    that keeps the bytes on S3 after the first download. Signed and bound
    to the transfer and file; it ages out with the grace window."""
    return signing.TimestampSigner(salt=RESUME_SIGNATURE_NAMESPACE).sign(
        f"{transfer.id}:{file_id}"
    )


def _resume_token_valid(token, transfer, file_id) -> bool:
    if not token:
        return False
    try:
        value = signing.TimestampSigner(salt=RESUME_SIGNATURE_NAMESPACE).unsign(
            token, max_age=timedelta(hours=settings.TRANSFER_PURGE_DELAY_HOURS)
        )
    except signing.BadSignature:
        return False
    return value == f"{transfer.id}:{file_id}"


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


def _resolve_recipient(transfer, request):
    """The recipient behind this visit, from the ``?r=<token>`` the emailed
    link carries. None for a bare link (copied from the sender's page,
    forwarded by hand, or emailed before tokens existed) and for a token
    that doesn't belong to this transfer — attribution is best-effort, a
    stale or foreign token must never turn into an error for the visitor."""
    token = request.query_params.get("r")
    if not token:
        return None
    return transfer.recipients.filter(token=token).first()


def _record_visitor_event(
    transfer, event_type, request, payload=None, recipient=None
) -> bool:
    """Journal a visitor action. Returns False when nothing was recorded:
    an authenticated agent visiting/downloading their own transfer —
    recipient activity is the audit signal here, owner self-checks aren't."""
    if request.user.is_authenticated and request.user.id == transfer.owner_id:
        return False
    models.TransferEvent.objects.create(
        transfer_id=transfer.id,
        recipient_id=recipient.id if recipient is not None else None,
        event_type=event_type,
        actor_type=ActorType.EXTERNAL,
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        payload=payload or {},
    )
    return True


def _maybe_send_download_receipt(transfer, recipient):
    """Queue the download receipt for the sender (opt-in per transfer, one
    email per recipient).

    * Every file fetched → enqueue now.
    * Otherwise → enqueue with a TRANSFER_DOWNLOAD_RECEIPT_DELAY countdown,
      at most once per recipient: the conditional UPDATE on
      ``delayed_receipt_armed_at`` succeeds for a single request, however
      many run concurrently. The email reports the files taken at send
      time.

    The task claims ``download_notified_at`` before sending, so only one
    of the queued tasks emails."""
    if not transfer.notify_on_download or recipient.download_notified_at:
        return
    file_count = transfer.files.count()
    if not file_count:
        return
    downloaded = files_downloaded_by(transfer.id, recipient.id)
    from core.tasks import send_download_receipt_task

    args = (str(transfer.id), str(recipient.id))
    if len(downloaded) >= file_count:
        transaction.on_commit(lambda: send_download_receipt_task.delay(*args))
        return
    armed = models.TransferRecipient.objects.filter(
        id=recipient.id, delayed_receipt_armed_at__isnull=True
    ).update(delayed_receipt_armed_at=timezone.now())
    if armed:
        transaction.on_commit(
            lambda: send_download_receipt_task.apply_async(
                args=args, countdown=settings.TRANSFER_DOWNLOAD_RECEIPT_DELAY
            )
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

        _record_visitor_event(
            transfer,
            TransferEventType.LINK_OPENED,
            request,
            recipient=_resolve_recipient(transfer, request),
        )
        serializer = DownloadTransferSerializer(transfer, context={"request": request})
        return Response(serializer.data)


class DownloadFileView(APIView):
    """Download a single file from a transfer."""

    permission_classes = [AllowAny]

    def get(self, request, public_token, file_id):
        transfer = _fetch_transfer_by_token(public_token)
        if transfer is None:
            return Response(TRANSFER_NOT_FOUND_BODY, status=404)

        # Resuming an interrupted download needs no special case on an
        # active transfer. The one place the access check would wrongly
        # refuse it is a one-shot transfer: its first full download flipped
        # the row to PENDING_FILE_DELETION, but the bytes stay on S3 until
        # ``pending_deletion_at`` precisely so in-flight downloads can
        # finish. A request carrying the resume capability issued with an
        # earlier download URL (``?resume=<token>``, sent by the decryption
        # Service Worker when it re-fetches) is let through during that
        # grace window; anyone else holding the link is still refused.
        resuming = _resume_token_valid(
            request.query_params.get("resume"), transfer, file_id
        )
        resume_grace = resuming and (
            transfer.status == TransferStatus.PENDING_FILE_DELETION
            and transfer.deactivation_reason == DeactivationReason.FIRST_DOWNLOAD
            and transfer.pending_deletion_at is not None
            and transfer.pending_deletion_at > timezone.now()
        )
        if not resume_grace:
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
        if transfer_file.scan_status not in (
            ScanStatus.CLEAN,
            ScanStatus.SKIPPED,
            ScanStatus.TOO_LARGE,
            ScanStatus.UNSCANNABLE,
        ):
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

        # Journaled like any other access (the event marks the moment a
        # presigned URL is handed out); a resume is flagged so the history
        # can show it as the continuation it is rather than a new download.
        recipient = _resolve_recipient(transfer, request)
        recorded = _record_visitor_event(
            transfer,
            TransferEventType.FILE_DOWNLOADED,
            request,
            payload={
                "file_id": str(transfer_file.id),
                "filename": transfer_file.filename,
                **({"resume": True} if resuming else {}),
            },
            recipient=recipient,
        )
        if recorded and recipient is not None:
            _maybe_send_download_receipt(transfer, recipient)

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
        if (
            transfer.auto_archive_on_download
            and transfer.status == TransferStatus.ACTIVE
        ):
            with transaction.atomic():
                locked = models.Transfer.objects.select_for_update().get(pk=transfer.pk)
                if (
                    locked.status == TransferStatus.ACTIVE
                    and _all_files_downloaded_once(locked)
                ):
                    if locked.deactivate(DeactivationReason.FIRST_DOWNLOAD):
                        models.TransferEvent.objects.create(
                            transfer_id=transfer.id,
                            event_type=TransferEventType.TRANSFER_DEACTIVATED_AFTER_FIRST_DOWNLOAD,
                            actor_type=ActorType.AGENT,
                        )

        # encryption callers (the decryption Service Worker) need the URL as data,
        # not a 302 — a cross-origin redirect from fetch() strips
        # credentials and trips CORS preflight quirks on Firefox. Opt into
        # JSON with ``?as=json`` so the SW can do a fresh anonymous GET to
        # the presigned URL on its own. The body carries a short-lived but
        # download-credential-equivalent URL, so forbid every cache layer
        # (browser, CDN, intermediate proxy) from retaining it.
        if request.query_params.get("as") == "json":
            response = Response(
                {"url": url, "resume": _resume_token(transfer, transfer_file.id)}
            )
            response["Cache-Control"] = "no-store"
            return response

        # Redirect the browser straight to S3 so the download bytes never
        # transit through a Django worker. The presigned URL's short expiry
        # limits the shelf life of the URL if it leaks (browser history,
        # logs, copy-paste).
        return HttpResponseRedirect(url)
