"""API ViewSet for TransferDraft — the ephemeral upload session.

A draft holds files-in-transit (and nothing else — no metadata) from the
first drop until the user clicks "Create link". At that point the finalize
action creates a fresh ``Transfer`` with the request body's metadata and
reparents the draft's ``TransferFile`` rows to it, then deletes the draft.
"""

import logging
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
from core.enums import ScanStatus, SharingMode, TransferEventType
from core.services import s3
from core.tasks import import_drive_file_task, submit_scan_task

logger = logging.getLogger(__name__)


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

    def _get_locked_draft(self, pk):
        """Like ``get_object`` but takes a row-level lock; must be called
        inside an ``atomic`` block so concurrent mutating ops on the same
        draft serialize."""
        try:
            return self.get_queryset().select_for_update().get(pk=pk)
        except models.TransferDraft.DoesNotExist as exc:
            raise drf.exceptions.NotFound("Draft not found.") from exc

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
                # Every transfer is encrypted, so the chunk size is always set
                # (server-imposed, settings.TRANSFER_CHUNK_SIZE, so the
                # recipient SW can never disagree with the encrypt path about
                # decryption boundaries). Whether the transfer ends up
                # confidential is decided only at finalize.
                draft = models.TransferDraft.objects.create(
                    owner=request.user,
                    encryption_chunk_size=settings.TRANSFER_CHUNK_SIZE,
                )
            else:
                draft = self._get_locked_draft(draft_id)

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
                plaintext_size=data["plaintext_size"],
                mime_type=data["mime_type"],
                source_url=data.get("source_url", ""),
            )
            transfer_file.s3_key = f"transfers/{transfer_file.id}/{data['filename']}"

            if transfer_file.source_url:
                # Drive import is deferred to finalize: encrypting the fetched
                # bytes server-side needs the key, and the key only reaches us
                # at finalize (non-confidential mode). Record the intent here
                # with no multipart and no fetch task; the client won't upload
                # parts, so it gets no ``upload_id`` / ``chunk_size`` back.
                # scan_status stays PENDING (the default) — the row will be
                # scanned like any other once the import lands. The finalize
                # scan-submission loop gates on ``upload_completed_at``, and
                # the 202 classifier reports ``drive_importing`` (not
                # ``scan_pending``) for rows still waiting on bytes.
                transfer_file.save()
            else:
                upload_id = s3.create_multipart_upload(
                    key=transfer_file.s3_key, content_type=data["mime_type"]
                )
                # If the save fails the atomic block rolls the row back, but
                # S3 keeps the MPU — abort it before re-raising.
                try:
                    transfer_file.upload_id = upload_id
                    transfer_file.save()
                except Exception:
                    # Don't let a S3 error here mask the original exception.
                    try:
                        s3.abort_multipart_upload(transfer_file.s3_key, upload_id)
                    except botocore.exceptions.ClientError:
                        logger.exception(
                            "Failed to abort orphan MPU %s for key %s after rollback",
                            upload_id,
                            transfer_file.s3_key,
                        )
                    raise

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
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Stash any failure detail and raise *outside* the atomic block, so
        # the cleanup it performs (draft.delete()) actually commits.
        error_detail = None

        with transaction.atomic():
            draft = self._get_locked_draft(pk)
            transfer_file = self._get_pending_file(draft, data["transfer_file_id"])

            try:
                s3.complete_multipart_upload(
                    key=transfer_file.s3_key,
                    upload_id=transfer_file.upload_id,
                    parts=data["parts"],
                )
            except botocore.exceptions.ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "Unknown")
                s3.best_effort_abort_multipart_uploads_from_files(draft.files.all())
                draft.delete()
                error_detail = {
                    "parts": (
                        f"S3 rejected the multipart upload completion "
                        f"({error_code}). The draft has been aborted, "
                        f"please restart it from scratch."
                    )
                }
            else:
                # Verify landed-size matches the declared one. See
                # viewsets/transfer.py history for the rationale; same guard.
                actual_size = s3.head_object_size(transfer_file.s3_key)
                if actual_size != transfer_file.size:
                    files = list(draft.files.all())
                    s3.best_effort_abort_multipart_uploads_from_files(files)
                    s3.best_effort_delete_objects_from_files(files)
                    draft.delete()
                    error_detail = {
                        "parts": (
                            f"Uploaded file size ({actual_size} bytes) does not "
                            f"match the declared size ({transfer_file.size} "
                            f"bytes). The draft has been aborted."
                        )
                    }
                else:
                    transfer_file.upload_completed_at = timezone.now()
                    transfer_file.upload_id = ""
                    if not settings.CLAMAV_SCAN_ENABLED:
                        transfer_file.scan_status = ScanStatus.SKIPPED
                    elif transfer_file.size > settings.SCAN_MAX_FILE_SIZE:
                        transfer_file.scan_status = ScanStatus.TOO_LARGE
                    transfer_file.save(
                        update_fields=[
                            "upload_completed_at",
                            "upload_id",
                            "scan_status",
                            "updated_at",
                        ]
                    )
                    # No scan here: S3 holds ciphertext and the key only
                    # arrives at finalize, which submits it.

        if error_detail is not None:
            raise drf.exceptions.ValidationError(error_detail)
        return drf.response.Response(status=204)

    @extend_schema(
        request=DraftRemoveFileSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="remove-file")
    def remove_file(self, request, pk=None):
        """Detach a file from a draft.

        S3 cleanup is best-effort: a backend hiccup is not something the
        user can fix by retrying, so the DB row is always removed and the
        orphan-sweep is the recovery path. If it was the last file, the
        draft itself is deleted — empty drafts have no reason to exist.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            draft = self._get_locked_draft(pk)
            try:
                transfer_file = draft.files.get(
                    id=serializer.validated_data["transfer_file_id"]
                )
            except models.TransferFile.DoesNotExist as exc:
                raise drf.exceptions.NotFound("Transfer file not found.") from exc

            files = [transfer_file]
            s3.best_effort_abort_multipart_uploads_from_files(files)
            s3.best_effort_delete_objects_from_files(files)

            transfer_file.delete()
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
        with transaction.atomic():
            draft = self._get_locked_draft(pk)
            files = list(draft.files.all())
            s3.best_effort_abort_multipart_uploads_from_files(files)
            s3.best_effort_delete_objects_from_files(files)
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

        The action is a 202 poll loop: it answers 202 while Drive imports
        or antivirus scans are in flight, and 200 with the Transfer once
        every file is settled. The whole body runs under the draft's row
        lock so concurrent re-posts see a consistent state.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metadata = serializer.validated_data
        confidential = metadata["confidential"]

        with transaction.atomic():
            draft = self._get_locked_draft(pk)
            files = list(draft.files.all())
            drive_files = [f for f in files if f.source_url]
            browser_files = [f for f in files if not f.source_url]

            self._reject_bad_finalize_shape(
                files, drive_files, browser_files, confidential
            )
            self._park_encryption_key(draft, metadata, confidential)

            drive_response = self._process_drive_imports(drive_files)
            if drive_response is not None:
                return drive_response

            self._submit_pending_scans(draft, files, confidential)
            scan_response = self._scan_gate(files)
            if scan_response is not None:
                return scan_response

            transfer = self._create_transfer_from_draft(draft, metadata, request)

        return drf.response.Response(TransferDetailSerializer(transfer).data)

    def _reject_bad_finalize_shape(
        self, files, drive_files, browser_files, confidential
    ):
        """Raise 400 for the three finalize-time invariants that the client
        could still violate: empty draft, Drive+confidential mix (the key
        would have to reach us to encrypt the fetched bytes), or a browser
        upload that never completed. Drive files are exempt from the last
        gate — they're expected pending until the import block below runs."""
        if not files:
            raise drf.exceptions.ValidationError(
                {"files": "Draft has no files to finalize."}
            )
        if drive_files and confidential:
            raise drf.exceptions.ValidationError(
                {
                    "confidential": (
                        "A confidential transfer cannot include a Drive "
                        "import (we would have to hold the key to encrypt "
                        "the fetched bytes). Remove the Drive file or turn "
                        "confidential off."
                    )
                }
            )
        pending = [str(f.id) for f in browser_files if f.upload_completed_at is None]
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

    def _park_encryption_key(self, draft, metadata, confidential):
        """Park the key on the draft so background workers (Drive import,
        scan submit) read it from the DB rather than receiving it as a
        Celery kwarg — which would surface it in task metadata and broker
        payloads. Confidential drafts never see the key, so this is a
        no-op for them. The row (and the key with it) is discarded when
        the Transfer is created at the end of ``finalize``."""
        if not confidential and not draft.encryption_key:
            draft.encryption_key = metadata["encryption_key"]
            draft.save(update_fields=["encryption_key", "updated_at"])

    def _process_drive_imports(self, drive_files):
        """Drive imports run at finalize (needs the key). The first call
        marks ``import_started_at`` and enqueues the import task; every
        re-post that finds files still importing returns 202 immediately.
        The transfer is created only once every Drive file has completed,
        so a finalized transfer never has a half-imported file.

        The 202 payload carries ``import_progress`` for each still-running
        file (``bytes_imported`` vs ``plaintext_size``) so the client can
        render a progress bar rather than an opaque spinner — the user is
        their own timeout: if the bar stops advancing they close the tab,
        and ``cleanup_abandoned_drafts_task`` reaps the orphaned draft
        24 h later. Worker-death is caught at the broker level by
        ``acks_late`` + ``reject_on_worker_lost`` on the task.

        Returns a 202/400 Response when the caller must return early, or
        ``None`` to let the outer flow continue to the scan phase.
        """
        if not drive_files:
            return None

        imported_failed = [
            str(f.id) for f in drive_files if f.import_failed_at is not None
        ]
        if imported_failed:
            raise drf.exceptions.ValidationError(
                {
                    "files": "A Drive import failed.",
                    "reason": "drive_import_failed",
                    "failed_file_ids": imported_failed,
                }
            )

        still_importing = []
        for f in drive_files:
            if f.upload_completed_at is not None:
                continue
            if f.import_started_at is None:
                # Not started yet — mark it and enqueue the encrypting
                # import. ``import_started_at`` keeps the next poll from
                # re-enqueuing while the task spins up its MPU.
                f.import_started_at = timezone.now()
                f.save(update_fields=["import_started_at", "updated_at"])
                transaction.on_commit(
                    lambda fid=str(f.id): import_drive_file_task.delay(fid)
                )
            still_importing.append(f)

        if still_importing:
            return drf.response.Response(
                {
                    "detail": "Drive files are still being imported.",
                    "reason": "drive_importing",
                    "pending_file_ids": [str(f.id) for f in still_importing],
                    "import_progress": [
                        {
                            "file_id": str(f.id),
                            "filename": f.filename,
                            # Bumped per-chunk by ``import_drive_file_task``;
                            # 0 before the first chunk lands. Frontend
                            # computes ``bytes_imported / plaintext_size``.
                            "bytes_imported": f.bytes_imported,
                            "plaintext_size": f.plaintext_size,
                        }
                        for f in still_importing
                    ],
                },
                status=202,
            )
        return None

    def _submit_pending_scans(self, draft, files, confidential):
        """Antivirus submission: confidential drafts mark every PENDING
        row SKIPPED (no key, unscannable — the recipient gets a lock icon
        instead of a "scanned" badge), non-confidential drafts enqueue a
        scan for each row whose bytes are on S3 and haven't been sent to
        the scanner yet. Idempotent: ``scan_submitted_at`` gates re-posts."""
        if not settings.CLAMAV_SCAN_ENABLED or not draft.encryption_chunk_size:
            return
        if confidential:
            for f in files:
                if f.scan_status == ScanStatus.PENDING:
                    f.scan_status = ScanStatus.SKIPPED
                    f.save(update_fields=["scan_status", "updated_at"])
            return
        # ``submit_scan_task`` decrypts with the key parked on the draft.
        for f in files:
            if (
                f.scan_status == ScanStatus.PENDING
                and f.upload_completed_at is not None
                and f.scan_submitted_at is None
            ):
                f.scan_submitted_at = timezone.now()
                f.save(update_fields=["scan_submitted_at", "updated_at"])
                transaction.on_commit(lambda fid=str(f.id): submit_scan_task.delay(fid))

    def _scan_gate(self, files):
        """Classify every file by scan status. A transfer is created only
        once every file is non-blocking (CLEAN, or scan-exempt SKIPPED /
        TOO_LARGE). Any INFECTED / ERROR fails the finalize; PENDING
        keeps the client polling. Re-arming a failed scan is /rescan/'s
        job — the reason strings are what the client keys its UI on.

        Returns a 202/400 Response when the caller must return early, or
        ``None`` to let the transfer creation proceed.
        """
        if not settings.CLAMAV_SCAN_ENABLED:
            return None

        infected, unscannable, scan_errored, scanning = [], [], [], []
        for f in files:
            if f.scan_status == ScanStatus.INFECTED:
                infected.append(str(f.id))
            elif f.scan_status == ScanStatus.ERROR:
                if f.scan_error_kind == "file":
                    unscannable.append(str(f.id))
                else:
                    scan_errored.append(str(f.id))
            elif f.scan_status == ScanStatus.PENDING:
                scanning.append(str(f.id))

        if infected:
            raise drf.exceptions.ValidationError(
                {
                    "files": "The antivirus scan blocked one or more files.",
                    "reason": "scan_blocked",
                    "blocked_file_ids": infected,
                }
            )
        if unscannable:
            raise drf.exceptions.ValidationError(
                {
                    "files": "One or more files could not be scanned.",
                    "reason": "scan_file_error",
                    "blocked_file_ids": unscannable,
                }
            )
        if scan_errored:
            raise drf.exceptions.ValidationError(
                {
                    "files": "The antivirus scan could not complete for one "
                    "or more files.",
                    "reason": "scan_error",
                    "blocked_file_ids": scan_errored,
                }
            )
        if scanning:
            return drf.response.Response(
                {
                    "detail": "Files are still being scanned for viruses.",
                    "reason": "scan_pending",
                    "pending_file_ids": scanning,
                },
                status=202,
            )
        return None

    def _create_transfer_from_draft(self, draft, metadata, request):
        """Build the Transfer from the draft's metadata, reparent every
        file in one UPDATE, schedule recipient emails on commit, and
        delete the draft. The Transfer is born fully-formed — the
        ``public_token`` is populated by its default and ``created_at``
        acts as the publication timestamp."""
        transfer = models.Transfer.objects.create(
            owner=draft.owner,
            title=metadata["title"],
            sharing_mode=metadata["sharing_mode"],
            expires_at=timezone.now()
            + timedelta(days=int(metadata["expires_in_days"])),
            auto_archive_on_download=metadata["auto_archive_on_download"],
            confidential=metadata["confidential"],
            # Read from the draft, not the request body — this is the same
            # value the Drive-import and scan tasks consumed, so recipients
            # get the exact key those workers used to encrypt / decrypt.
            # Empty for confidential (parking skips it, the serializer also
            # enforces an empty body key).
            encryption_key=draft.encryption_key,
            encryption_chunk_size=draft.encryption_chunk_size,
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
        return transfer

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="DraftRescanResponse",
                fields={
                    "rescanned_file_ids": serializers.ListField(
                        child=serializers.UUIDField()
                    )
                },
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="rescan")
    def rescan(self, request, pk=None):
        """Re-submit a draft's stuck files to the antivirus scanner.

        When the scanner is unreachable, ``submit_scan_task`` exhausts its
        retries and dies (or a webhook is lost), leaving files PENDING with no
        job in flight until the 5-minute reaper eventually catches them. This
        lets the user re-arm the scan on demand instead of waiting — it's what
        the front's "retry" affordance calls when its poller has given up.
        Files under a hard block (INFECTED, or a file-bound ERROR) are left
        untouched: retrying can't help them.
        """
        if not settings.CLAMAV_SCAN_ENABLED:
            return drf.response.Response({"rescanned_file_ids": []})

        with transaction.atomic():
            draft = self._get_locked_draft(pk)
            rescanned = []
            for f in draft.files.filter(upload_completed_at__isnull=False):
                is_pending = f.scan_status == ScanStatus.PENDING
                is_transient = (
                    f.scan_status == ScanStatus.ERROR and f.scan_error_kind != "file"
                )
                if not (is_pending or is_transient):
                    continue
                if is_transient:
                    # Mirror the finalize gate: a transient error goes back to
                    # PENDING before re-submitting.
                    f.scan_status = ScanStatus.PENDING
                    f.scan_error_kind = ""
                # Re-arm the marker, else finalize thinks it's still in flight.
                f.scan_submitted_at = timezone.now()
                f.save(
                    update_fields=[
                        "scan_status",
                        "scan_error_kind",
                        "scan_submitted_at",
                        "updated_at",
                    ]
                )
                transaction.on_commit(lambda fid=str(f.id): submit_scan_task.delay(fid))
                rescanned.append(str(f.id))

        logger.info(
            "Rescan requested for draft %s: re-submitted %d file(s) %s",
            pk,
            len(rescanned),
            rescanned,
        )
        return drf.response.Response({"rescanned_file_ids": rescanned})


# --- Helpers ---
