"""Inbound webhook from the file-scanner service.

The scanner POSTs the result of an asynchronous scan here once it finishes.
The endpoint is unauthenticated in the Django sense (the scanner has no
account) but protected by a per-file opaque secret minted at submission time
and echoed back in the query string — compared in constant time before any
state change. Updates are guarded to PENDING files, so a terminal verdict is
final: a replayed or duplicate callback (a scanner retry, or a second scan job
from the reaper) is a 200 no-op rather than an overwrite.
"""

import hmac
import logging

from django.core.exceptions import ValidationError

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.enums import ScanStatus

logger = logging.getLogger(__name__)


class ScanResultWebhookView(APIView):
    """POST /webhooks/scan-result/?file_id=<uuid>&secret=<token>

    Body is the scanner's job payload: ``{status, verdicts, scanners, ...}``.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        file_id = request.query_params.get("file_id")
        secret = request.query_params.get("secret", "")

        if not file_id:
            return Response({"detail": "file_id is required."}, status=400)

        try:
            transfer_file = models.TransferFile.objects.get(id=file_id)
        except (models.TransferFile.DoesNotExist, ValueError, ValidationError):
            # File deleted (uploaded then removed) or malformed id. Ack with
            # 200 so the scanner treats it as delivered and stops retrying —
            # there is genuinely nothing left to update.
            logger.info("Scan webhook for unknown/removed file %s — acking", file_id)
            return Response(status=200)

        # Constant-time compare; reject if the file has no secret (never
        # submitted for scan) or the token doesn't match.
        if not transfer_file.webhook_secret or not hmac.compare_digest(
            secret, transfer_file.webhook_secret
        ):
            logger.warning("Scan webhook with bad secret for file %s", file_id)
            return Response({"detail": "Invalid secret."}, status=403)

        payload = request.data
        new_status = self._status_from_payload(payload)
        error_kind = self._error_kind_from_payload(payload, new_status)

        # Only a PENDING file is mutable — every legitimate result lands while a
        # scan is in flight. Guarding on it makes a terminal verdict final, so a
        # stale or duplicate callback (scanner retry, or a second reaper job)
        # can't overwrite it: fail closed, a virus stays a virus.
        updated = models.TransferFile.objects.filter(
            id=transfer_file.id, scan_status=ScanStatus.PENDING
        ).update(
            scan_status=new_status,
            scan_error_kind=error_kind,
            scan_report=self._report(payload),
        )
        if not updated:
            logger.info(
                "Scan result for file %s ignored — already %s",
                file_id,
                transfer_file.scan_status,
            )
            return Response(status=200)
        logger.info(
            "Scan result for file %s: %s%s%s",
            file_id,
            new_status,
            f" ({error_kind})" if error_kind else "",
            self._engines_summary(payload),
        )
        return Response(status=200)

    # Kept out of the report: job_id and filename are already columns, and the
    # metadata we sent back to ourselves says nothing about the file.
    _REPORT_KEYS = (
        "api_version",
        "status",
        "verdicts",
        "scanners",
        "error_kind",
        "error",
    )

    @classmethod
    def _report(cls, payload) -> dict:
        """The part of the callback that explains the decision, for the audit
        trail. Empty for a body we cannot read — the status already says so."""
        if not isinstance(payload, dict):
            return {}
        return {k: payload[k] for k in cls._REPORT_KEYS if k in payload}

    @staticmethod
    def _engines_summary(payload) -> str:
        """What each engine said, for the log: `` [clamav=clean, exav=malware:Sig]``.
        Empty when the payload has no per-scanner report."""
        reports = payload.get("scanners") if isinstance(payload, dict) else None
        if not isinstance(reports, list):
            return ""
        parts = []
        for report in reports:
            if not isinstance(report, dict):
                continue
            entry = f"{report.get('scanner')}={report.get('kind')}"
            if report.get("reason"):
                entry += f":{report['reason']}"
            parts.append(entry)
        return f" [{', '.join(parts)}]" if parts else ""

    # Verdict words the scanner sends that this version has no status for.
    # Unlike a word we have never heard of, these are known to be terminal.
    _UNMAPPABLE_VERDICTS = ("flagged",)

    @staticmethod
    def _verdict_kind(payload):
        """The malware axis's verdict word, or None when the body has none.

        A non-string ``kind`` (a list, an object) is unhashable: looking it up
        in a dict would raise and answer 500, which the scanner reads as a
        failed delivery and retries until it dead-letters.
        """
        verdicts = payload.get("verdicts")
        verdict = verdicts.get("malware") if isinstance(verdicts, dict) else None
        if not isinstance(verdict, dict):
            return None
        kind = verdict.get("kind")
        return kind if isinstance(kind, str) else None

    @classmethod
    def _error_kind_from_payload(cls, payload, status) -> str:
        """Sub-classify an ERROR as 'file' (unscannable — the user must remove
        it) or 'transient' (retryable). Ambiguous bodies default to transient
        so a passing outage isn't blamed on the file; empty for non-error
        statuses so a recovered file clears any stale kind.

        That default carries the ``error`` verdict: the scan ran, so the body
        has ``status: "done"`` and no ``error_kind`` at all — and an engine
        that failed is exactly the transient case. Only a *pre-scan* failure
        (bad host, download error, undecryptable file) sends ``error_kind``
        itself, and only it can say ``file``.
        """
        if status != ScanStatus.ERROR or not isinstance(payload, dict):
            return ""
        # A verdict we cannot map is still a verdict: the scan concluded, so a
        # retry returns the same word. Permanent, or /rescan/ loops on it.
        if cls._verdict_kind(payload) in cls._UNMAPPABLE_VERDICTS:
            return "file"
        kind = payload.get("error_kind")
        return kind if kind in ("transient", "file") else "transient"

    # The scanner's verdict for the malware axis → this file's scan status.
    # ``flagged`` (a content-policy hit) is left out on purpose: INFECTED
    # would call it a virus. It falls through below, blocking without naming.
    _VERDICT_STATUS = {
        "clean": ScanStatus.CLEAN,
        "malware": ScanStatus.INFECTED,
        # The scan ran; the file itself (an encrypted or unreadable container)
        # is why there is no answer. Not a detection, and no retry will change
        # it: scan-exempt, with a warning.
        "partial": ScanStatus.UNSCANNABLE,
        "error": ScanStatus.ERROR,
    }

    @classmethod
    def _status_from_payload(cls, payload) -> str:
        """Map the scanner's payload onto a ``ScanStatus``.

        The malware axis arrives as ``verdicts.malware.kind``, in the words the
        engines themselves use — ``clean`` / ``malware`` / ``partial`` /
        ``error``. It replaces the flat ``malware`` tri-state, which the
        scanner no longer sends at all: only the verdict separates "this
        file cannot be read" (permanent, the sender must drop it) from "the
        engines failed" (retryable).

        Fails closed throughout: a job-level ``error``, a verdict word we don't
        know, a body carrying no verdict at all, or any malformed one maps to
        ERROR rather than CLEAN, so a botched scan never unlocks a download.
        A scanner too old to report verdicts therefore blocks every file it
        answers for, and this version blocks every file a newer scanner
        answers for. That cuts both ways by design: there is no deployment
        order that spans the change, so the two services ship together and
        the gap is a short refusal of every scan, never a silent pass.
        """
        if not isinstance(payload, dict):
            return ScanStatus.ERROR
        if payload.get("status") == "error":
            # The job never reached a verdict (the file couldn't be fetched, or
            # no deciding engine was up). Nothing in the body is worth reading.
            return ScanStatus.ERROR
        kind = cls._verdict_kind(payload)
        if kind is None:
            return ScanStatus.ERROR
        return cls._VERDICT_STATUS.get(kind, ScanStatus.ERROR)
