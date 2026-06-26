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
                # E2E params are honoured here only; subsequent add-file calls
                # ignore them — the mode is locked the moment the draft exists.
                draft = models.TransferDraft.objects.create(
                    owner=request.user,
                    e2e_encrypted=data.get("e2e_encrypted", False),
                    encryption_chunk_size=data.get("encryption_chunk_size"),
                )
            else:
                draft = self._get_locked_draft(draft_id)

                # The draft's E2E mode is locked at creation; reject mismatched
                # follow-up calls instead of letting a plaintext file slip into
                # an encrypted draft (or vice versa).
                if data.get("e2e_encrypted", False) != draft.e2e_encrypted:
                    raise drf.exceptions.ValidationError(
                        {
                            "e2e_encrypted": (
                                "Cannot change encryption mode once a draft has "
                                "been started."
                            )
                        }
                    )
                # Same lock on chunk size: the recipient's SW computes part
                # boundaries from one constant value across all files in the
                # transfer. A follow-up call that ships a different value
                # would silently de-sync the boundaries.
                if (
                    draft.e2e_encrypted
                    and data["encryption_chunk_size"] != draft.encryption_chunk_size
                ):
                    raise drf.exceptions.ValidationError(
                        {
                            "encryption_chunk_size": (
                                "Cannot change chunk size once a draft has "
                                "been started."
                            )
                        }
                    )

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
                plaintext_size=data.get("plaintext_size") if draft.e2e_encrypted else None,
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
                            "Failed to abort orphan MPU %s for key %s after "
                            "rollback",
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
                    # No scan coming → mark SKIPPED (downloadable, no "clean"
                    # claim), else it stays PENDING forever (perpetual spinner +
                    # blocked download). Scanning on → PENDING until the webhook.
                    # E2E ciphertext can't be scanned (we don't have the key),
                    # so the gate is bypassed wholesale — same SKIPPED status.
                    if draft.e2e_encrypted or not settings.CLAMAV_SCAN_ENABLED:
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
                    # on_commit so the scanner never races the transaction.
                    # PENDING ⟺ AV on AND within size limit (the only case that
                    # needs a scan — SKIPPED / TOO_LARGE were set above).
                    if transfer_file.scan_status == ScanStatus.PENDING:
                        file_id = str(transfer_file.id)
                        transaction.on_commit(
                            lambda fid=file_id: submit_scan_task.delay(fid)
                        )

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

        Refuses to finalize a draft whose files haven't all completed their
        multipart upload (``upload_completed_at IS NULL`` on a per-file basis).
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metadata = serializer.validated_data

        with transaction.atomic():
            draft = self._get_locked_draft(pk)

            # key_fragment is only meaningful when the draft is E2E and the
            # transfer is being sent by email; the serializer already gates
            # it against link mode. Cross-check against the draft's mode
            # here: requiring it when expected catches a buggy client that
            # would otherwise post emails without a decryption link, and
            # rejecting it when not expected matches the rest of the E2E
            # parameter hygiene.
            mode = metadata.get("sharing_mode", SharingMode.LINK)
            posted_fragment = metadata.get("key_fragment", "")
            if mode == SharingMode.EMAIL:
                if draft.e2e_encrypted and not posted_fragment:
                    raise drf.exceptions.ValidationError(
                        {
                            "key_fragment": (
                                "Required when finalizing an E2E draft in "
                                "email mode."
                            )
                        }
                    )
                if not draft.e2e_encrypted and posted_fragment:
                    raise drf.exceptions.ValidationError(
                        {"key_fragment": "Only allowed for E2E drafts."}
                    )

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

            # Antivirus gate (fail closed): a draft only becomes a transfer once
            # every file has a non-blocking status — CLEAN, or scan-exempt
            # (SKIPPED / TOO_LARGE). Two hard blocks: a virus, and a file that
            # can't be scanned (error_kind="file") — a retry won't help, the
            # user must remove it. A *transient* error (clamd/scanner hiccup) is
            # re-submitted and kept polling so a passing failure doesn't brick
            # the draft — the client's overall timeout bounds the retries. A
            # broken scanner thus never sends, but recovers on its own.
            if settings.CLAMAV_SCAN_ENABLED:
                infected, unscannable, transient_errored, scanning = [], [], [], []
                for f in files:
                    if f.scan_status == ScanStatus.INFECTED:
                        infected.append(str(f.id))
                    elif f.scan_status == ScanStatus.ERROR:
                        if f.scan_error_kind == "file":
                            unscannable.append(str(f.id))
                        else:
                            transient_errored.append(f)
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
                for f in transient_errored:
                    f.scan_status = ScanStatus.PENDING
                    f.scan_error_kind = ""
                    f.save(
                        update_fields=[
                            "scan_status",
                            "scan_error_kind",
                            "updated_at",
                        ]
                    )
                    transaction.on_commit(
                        lambda fid=str(f.id): submit_scan_task.delay(fid)
                    )
                    scanning.append(str(f.id))

                if scanning:
                    return drf.response.Response(
                        {
                            "detail": "Files are still being scanned for viruses.",
                            "reason": "scan_pending",
                            "pending_file_ids": scanning,
                        },
                        status=202,
                    )

            transfer = models.Transfer.objects.create(
                owner=draft.owner,
                title=metadata["title"],
                sharing_mode=metadata["sharing_mode"],
                expires_at=timezone.now()
                + timedelta(days=int(metadata["expires_in_days"])),
                auto_archive_on_download=metadata["auto_archive_on_download"],
                e2e_encrypted=draft.e2e_encrypted,
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

                # E2E + email: the key fragment travels via Celery kwarg
                # to the send task. Not persisted on Transfer — once emails
                # are sent it lives only in the recipients' inboxes.
                key_fragment = (
                    metadata.get("key_fragment", "") if transfer.e2e_encrypted else ""
                )
                transaction.on_commit(
                    lambda fragment=key_fragment: send_recipient_invitations_task.delay(
                        str(transfer.id), key_fragment=fragment
                    )
                )

            draft.delete()

        detail = TransferDetailSerializer(transfer)
        return drf.response.Response(detail.data)


# --- Helpers ---
