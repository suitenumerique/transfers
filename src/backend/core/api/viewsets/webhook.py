"""Inbound webhook from the clamav file-scanner service.

The scanner POSTs the result of an asynchronous scan here once it finishes.
The endpoint is unauthenticated in the Django sense (the scanner has no
account) but protected by a per-file opaque secret minted at submission time
and echoed back in the query string — compared in constant time before any
state change. The handler is idempotent: replaying the same callback (e.g. a
scanner retry) simply re-writes the same ``scan_status``.
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

    Body is the scanner's job payload: ``{status, malware, reason, ...}``.
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

        models.TransferFile.objects.filter(id=transfer_file.id).update(
            scan_status=new_status, scan_error_kind=error_kind
        )
        logger.info(
            "Scan result for file %s: %s%s",
            file_id,
            new_status,
            f" ({error_kind})" if error_kind else "",
        )
        return Response(status=200)

    @staticmethod
    def _error_kind_from_payload(payload, status) -> str:
        """Sub-classify an ERROR as 'file' (unscannable — the user must remove
        it) or 'transient' (retryable). Ambiguous bodies default to transient
        so a passing outage isn't blamed on the file; empty for non-error
        statuses so a recovered file clears any stale kind.
        """
        if status != ScanStatus.ERROR or not isinstance(payload, dict):
            return ""
        kind = payload.get("error_kind")
        return kind if kind in ("transient", "file") else "transient"

    @staticmethod
    def _status_from_payload(payload) -> str:
        """Map the scanner's payload onto a ``ScanStatus``.

        Fails closed: an ``error`` status, or any malformed/ambiguous body,
        maps to ERROR rather than CLEAN so a botched scan never unlocks a
        download.
        """
        if not isinstance(payload, dict):
            return ScanStatus.ERROR
        if payload.get("status") == "error":
            return ScanStatus.ERROR
        malware = payload.get("malware")
        if malware is True:
            return ScanStatus.INFECTED
        if malware is False:
            return ScanStatus.CLEAN
        return ScanStatus.ERROR
