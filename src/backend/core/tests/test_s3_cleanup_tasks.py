"""Integration tests — S3 cleanup driven by Celery tasks.

Same contract as ``test_s3_cleanup_drafts.py``: each test runs a real
task end-to-end against a moto-backed bucket and asserts the bucket is
*actually* empty after.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.utils import timezone

import botocore
import pytest
import requests

from core.enums import TransferStatus
from core.factories import TransferDraftFactory, TransferFactory, TransferFileFactory
from core.models import TransferDraft, TransferFile
from core.tasks import (
    _DRIVE_IMPORT_CHUNK_SIZE,
    cleanup_abandoned_drafts_task,
    deactivate_expired_transfers_task,
    delete_pending_transfer_files_task,
    import_drive_file_task,
)
from core.tests._s3_live import assert_bucket_empty, seed_mpu


@pytest.mark.django_db
class TestCleanupAbandonedDraftsTask:
    """The 24h sweep is the last line of defense against drafts the user
    abandoned (browser closed, network died). If it leaks, nothing else
    catches the orphans."""

    def test_clears_partial_mpu_on_old_draft(self, user, live_s3_bucket):
        bucket = settings.TRANSFERS_BUCKET_NAME
        draft = TransferDraftFactory(owner=user)
        TransferDraft.objects.filter(id=draft.id).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        # Seed an in-progress MPU directly so the DB row matches what S3
        # holds — the task's contract is "abort whatever upload_id points to".
        key = f"transfers/{draft.id}/abandoned.bin"
        upload_id = seed_mpu(live_s3_bucket, bucket, key, n_parts=2)
        TransferFileFactory(
            transfer=None, draft=draft, upload_id=upload_id, s3_key=key
        )

        cleanup_abandoned_drafts_task()

        assert not TransferDraft.objects.filter(id=draft.id).exists()
        assert_bucket_empty(live_s3_bucket, bucket)

    def test_clears_completed_object_on_old_draft(self, user, live_s3_bucket):
        bucket = settings.TRANSFERS_BUCKET_NAME
        draft = TransferDraftFactory(owner=user)
        TransferDraft.objects.filter(id=draft.id).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        key = f"transfers/{draft.id}/sealed.bin"
        live_s3_bucket.put_object(Bucket=bucket, Key=key, Body=b"sealed")
        TransferFileFactory(
            transfer=None,
            draft=draft,
            s3_key=key,
            upload_completed_at=timezone.now(),
        )

        cleanup_abandoned_drafts_task()

        assert_bucket_empty(live_s3_bucket, bucket)

    def test_leaves_young_draft_alone(self, user, live_s3_bucket):
        # The young draft's S3 state must SURVIVE the sweep — this is the
        # safety side of the cron. Drafts that the user is still working
        # on must not be torn down.
        bucket = settings.TRANSFERS_BUCKET_NAME
        draft = TransferDraftFactory(owner=user)
        key = f"transfers/{draft.id}/young.bin"
        upload_id = seed_mpu(live_s3_bucket, bucket, key, n_parts=1)
        TransferFileFactory(
            transfer=None, draft=draft, upload_id=upload_id, s3_key=key
        )

        cleanup_abandoned_drafts_task()

        assert TransferDraft.objects.filter(id=draft.id).exists()
        uploads = live_s3_bucket.list_multipart_uploads(Bucket=bucket).get("Uploads") or []
        assert len(uploads) == 1


@pytest.mark.django_db
class TestImportDriveFileTaskLeaks:
    """Server-side Drive import — failures at any point in the streaming
    pipeline must leave the bucket clean."""

    def _make_drive_file(self, user, declared_size: int) -> TransferFile:
        draft = TransferDraftFactory(owner=user)
        return TransferFileFactory(
            transfer=None,
            draft=draft,
            filename="from-drive.bin",
            size=declared_size,
            source_url="https://fichiers.example.gouv.fr/api/v1.0/items/x/download/",
        )

    def test_request_failure_mid_stream_leaves_no_orphan_mpu(
        self, user, live_s3_bucket
    ):
        bucket = settings.TRANSFERS_BUCKET_NAME
        # Declare a size big enough to fit the two chunks we're about to
        # stream plus some, so the failure happens inside the streaming
        # loop and not at the post-loop size check.
        tf = self._make_drive_file(user, declared_size=3 * _DRIVE_IMPORT_CHUNK_SIZE)

        # Mock the streaming response: yield two chunks, then raise — the
        # realistic "Drive dropped the connection mid-download" shape, with
        # multiple parts already uploaded to S3 that need aborting.
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        def _iter_two_then_raise(chunk_size):
            yield b"x" * chunk_size
            yield b"x" * chunk_size
            raise requests.exceptions.ChunkedEncodingError("connection dropped")

        mock_resp.iter_content.side_effect = _iter_two_then_raise
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("core.tasks.requests.get", return_value=mock_resp):
            import_drive_file_task(str(tf.id))

        assert not TransferFile.objects.filter(id=tf.id).exists()
        assert_bucket_empty(live_s3_bucket, bucket)

    def test_size_mismatch_after_full_stream_leaves_no_orphan(
        self, user, live_s3_bucket
    ):
        # Drive returned fewer bytes than declared: the task's own size check
        # raises ValueError, which the except clause turns into the same
        # abort + delete + tf.delete cleanup.
        bucket = settings.TRANSFERS_BUCKET_NAME
        # Declared size is larger than what we'll actually emit, so the
        # task's post-stream size check fires.
        tf = self._make_drive_file(user, declared_size=3 * _DRIVE_IMPORT_CHUNK_SIZE)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        def _iter_short(chunk_size):
            # Only emit one chunk's worth — declared size is larger, so the
            # task raises at the post-stream size check.
            yield b"y" * chunk_size

        mock_resp.iter_content.side_effect = _iter_short
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("core.tasks.requests.get", return_value=mock_resp):
            import_drive_file_task(str(tf.id))

        assert not TransferFile.objects.filter(id=tf.id).exists()
        assert_bucket_empty(live_s3_bucket, bucket)

    def test_stream_dies_before_any_part_lands(self, user, live_s3_bucket):
        # Failure happens after create_multipart_upload succeeded but before
        # any chunk reached the buffer threshold to be uploaded as a part.
        # The MPU exists in S3 with zero parts — abort must still target it.
        bucket = settings.TRANSFERS_BUCKET_NAME
        # Declared size is irrelevant here — the iterator raises before any
        # byte is streamed — but keep it consistent with the other tests.
        tf = self._make_drive_file(user, declared_size=3 * _DRIVE_IMPORT_CHUNK_SIZE)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        def _immediate_raise(chunk_size):
            raise requests.exceptions.ConnectionError("drive went away")
            yield  # pragma: no cover

        mock_resp.iter_content.side_effect = _immediate_raise
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("core.tasks.requests.get", return_value=mock_resp):
            import_drive_file_task(str(tf.id))

        assert not TransferFile.objects.filter(id=tf.id).exists()
        assert_bucket_empty(live_s3_bucket, bucket)

    def test_complete_multipart_failure_leaves_no_orphan(
        self, user, live_s3_bucket
    ):
        # Stream succeeds end-to-end and the size matches, but S3 rejects
        # CompleteMultipartUpload (e.g. an inconsistent ETag set). The
        # except clause must abort the (now uncomplete) MPU and delete any
        # partial object.
        bucket = settings.TRANSFERS_BUCKET_NAME
        # One chunk fully streamed, declared size matches — so the post-stream
        # size check passes and we reach CompleteMultipartUpload.
        tf = self._make_drive_file(user, declared_size=_DRIVE_IMPORT_CHUNK_SIZE)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        def _one_chunk(chunk_size):
            yield b"y" * chunk_size

        mock_resp.iter_content.side_effect = _one_chunk
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        forced_error = botocore.exceptions.ClientError(
            {"Error": {"Code": "InvalidPart", "Message": "forced"}},
            "CompleteMultipartUpload",
        )

        with (
            patch("core.tasks.requests.get", return_value=mock_resp),
            patch(
                "core.tasks.s3.complete_multipart_upload",
                side_effect=forced_error,
            ),
        ):
            import_drive_file_task(str(tf.id))

        assert not TransferFile.objects.filter(id=tf.id).exists()
        assert_bucket_empty(live_s3_bucket, bucket)

    def test_db_save_failure_after_mpu_created_leaves_no_orphan(
        self, user, live_s3_bucket
    ):
        # The save right after create_multipart_upload (line that persists
        # s3_key + upload_id) is the analogue of the add_file rollback hole:
        # a DB hiccup here used to escape the narrow except tuple and leak
        # the freshly-created MPU.
        bucket = settings.TRANSFERS_BUCKET_NAME
        tf = self._make_drive_file(user, declared_size=_DRIVE_IMPORT_CHUNK_SIZE)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = iter([])
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        original_save = TransferFile.save

        def _raise_on_first_post_mpu_save(self, *args, **kwargs):
            # The first save after create_multipart_upload sets upload_id;
            # any later tf.delete()-driven cleanup keeps working.
            if self.upload_id and self.upload_completed_at is None:
                raise RuntimeError("simulated DB hiccup post-MPU-create")
            return original_save(self, *args, **kwargs)

        with (
            patch("core.tasks.requests.get", return_value=mock_resp),
            patch.object(TransferFile, "save", _raise_on_first_post_mpu_save),
        ):
            import_drive_file_task(str(tf.id))

        assert not TransferFile.objects.filter(id=tf.id).exists()
        assert_bucket_empty(live_s3_bucket, bucket)


@pytest.mark.django_db
class TestExpireTransfersTask:
    """Cron sweep for expired transfers — two-step: flag then purge S3."""

    def test_clears_completed_objects_on_expired_transfer(
        self, user, live_s3_bucket
    ):
        bucket = settings.TRANSFERS_BUCKET_NAME
        transfer = TransferFactory(
            owner=user, expires_at=timezone.now() - timedelta(hours=1)
        )
        # Two completed files, both with real S3 backing.
        for i in range(2):
            key = f"transfers/{transfer.id}/sealed-{i}.bin"
            live_s3_bucket.put_object(Bucket=bucket, Key=key, Body=b"sealed")
            TransferFileFactory(
                transfer=transfer,
                s3_key=key,
                upload_completed_at=timezone.now() - timedelta(hours=2),
            )

        # Step 1: flag as pending deletion (grace window starts).
        deactivate_expired_transfers_task()
        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.PENDING_FILE_DELETION

        # Step 2: bypass the grace window and run the purge task.
        transfer.pending_deletion_at = timezone.now() - timedelta(seconds=1)
        transfer.save(update_fields=["pending_deletion_at"])
        delete_pending_transfer_files_task()

        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.DEACTIVATED
        assert_bucket_empty(live_s3_bucket, bucket)

    def test_leaves_active_transfer_alone(self, user, live_s3_bucket):
        bucket = settings.TRANSFERS_BUCKET_NAME
        transfer = TransferFactory(
            owner=user, expires_at=timezone.now() + timedelta(days=1)
        )
        key = f"transfers/{transfer.id}/keep.bin"
        live_s3_bucket.put_object(Bucket=bucket, Key=key, Body=b"keep")
        TransferFileFactory(
            transfer=transfer, s3_key=key, upload_completed_at=timezone.now()
        )

        deactivate_expired_transfers_task()

        transfer.refresh_from_db()
        assert transfer.status == TransferStatus.ACTIVE
        objects = live_s3_bucket.list_objects_v2(Bucket=bucket).get("Contents") or []
        assert len(objects) == 1
