"""API views for deposits: files sent to an agent by someone without an
account (see ``core.services.deposits``).

Agents manage their deposit spaces at ``/deposit-spaces/``. The public side
runs without authentication: a depositor reads a space, asks for a one-time
code (``/deposit-challenges/``), verifies it, then uploads through
``/deposit-drafts/`` with the session token it got back, in the
``X-Deposit-Token`` header.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, prefetch_related_objects
from django.utils import timezone

import rest_framework as drf
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core import models
from core.api.permissions import (
    DepositCapabilityPermission,
    IsAuthenticated,
    deposits_closed_body,
    enforce_upload_entitlement,
)
from core.api.serializers import (
    DepositAddFileSerializer,
    DepositChallengeCreateSerializer,
    DepositFinalizeSerializer,
    DepositReceiptSerializer,
    DepositSpaceSerializer,
    DepositVerifySerializer,
    InboxClaimSerializer,
    PublicDepositSpaceSerializer,
)
from core.api.throttling import (
    DepositChallengeEmailThrottle,
    DepositChallengeThrottle,
    DepositPublicThrottle,
    DepositVerifyThrottle,
)
from core.api.utils import log_agent_event
from core.api.viewsets import Pagination
from core.api.viewsets.draft import TransferDraftViewSet
from core.enums import (
    ActorType,
    SharingMode,
    TransferDirection,
    TransferEventType,
    TransferStatus,
)
from core.services import deposits
from core.services.email import send_deposit_otp
from core.tasks import send_deposit_notification_task, send_deposit_receipt_task

logger = logging.getLogger(__name__)

NOT_FOUND_BODY = {"detail": "Deposit space not found.", "reason": "not_found"}
REVOKED_BODY = {"detail": "This deposit space was closed.", "reason": "revoked"}


def _open_space_or_response(link_token):
    """The space behind a link, or the 404/410 Response to answer instead.
    A space whose owner was deactivated reads as unknown."""
    space = (
        models.DepositSpace.objects.select_related("owner")
        .filter(link_token=link_token, owner__is_active=True)
        .first()
    )
    if space is None:
        return None, Response(NOT_FOUND_BODY, status=404)
    if space.revoked_at is not None:
        return None, Response(REVOKED_BODY, status=410)
    return space, None


class DepositSpaceViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """An agent's deposit spaces. No delete: a space is revoked, and its
    deposits live out their retention."""

    permission_classes = [IsAuthenticated]
    serializer_class = DepositSpaceSerializer
    pagination_class = Pagination
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        return (
            models.DepositSpace.objects.filter(owner=self.request.user)
            # Only active deposits count: the sidebar hides a closed space
            # once none of its deposits can still be downloaded.
            .annotate(
                deposit_count=Count(
                    "deposits", filter=Q(deposits__status=TransferStatus.ACTIVE)
                )
            )
            # Open spaces (revoked_at NULL) first; Postgres would put them last.
            .order_by(F("revoked_at").asc(nulls_first=True), "-created_at")
        )

    def perform_create(self, serializer):
        enforce_upload_entitlement(self.request.user)
        space = serializer.save(owner=self.request.user)
        # The serializer reads the annotation.
        space.deposit_count = 0

    def perform_update(self, serializer):
        if serializer.instance.revoked_at is not None:
            raise drf.exceptions.ValidationError(
                {"revoked_at": "A closed space cannot be changed."}
            )
        serializer.save()

    @extend_schema(request=None, responses={200: DepositSpaceSerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        """Close the link. Deposits already received stay until they expire."""
        space = self.get_object()
        if space.revoked_at is None:
            space.revoked_at = timezone.now()
            space.save(update_fields=["revoked_at", "updated_at"])
        return Response(self.get_serializer(space).data)


class PublicDepositSpaceView(APIView):
    """GET /public-deposit-spaces/<link_token>/: what the deposit page shows."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [DepositPublicThrottle]

    @extend_schema(responses={200: PublicDepositSpaceSerializer})
    def get(self, request, link_token):
        space, denied = _open_space_or_response(link_token)
        if denied is not None:
            return denied
        return Response(PublicDepositSpaceSerializer(space).data)


class DepositChallengeView(APIView):
    """POST /deposit-challenges/: email a one-time code to the depositor.

    The answer is the same whether the target agent has an account or not,
    so the endpoint tells nobody who uses the app."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [DepositChallengeThrottle, DepositChallengeEmailThrottle]

    @extend_schema(request=DepositChallengeCreateSerializer)
    def post(self, request):
        serializer = DepositChallengeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        space = None
        if data.get("space_token"):
            space, denied = _open_space_or_response(data["space_token"])
            if denied is not None:
                return denied
            # Report the space as closed, without the reason the owner lost access.
            try:
                enforce_upload_entitlement(space.owner)
            except drf.exceptions.PermissionDenied:
                return Response(REVOKED_BODY, status=410)
        else:
            if not deposits.inbox_enabled():
                return Response(
                    {"detail": "Anonymous sends are disabled.", "reason": "disabled"},
                    status=404,
                )
            if not deposits.inbox_email_allowed(data["recipient_email"]):
                return Response(
                    {
                        "recipient_email": "This address cannot receive files here.",
                        "reason": "recipient_not_allowed",
                    },
                    status=400,
                )
        target = deposits.target_key(
            space.id if space else None, data.get("recipient_email", "")
        )

        try:
            # Codes are only sent here, so this limit is only enforced here.
            deposits.check_code_requests(data["depositor_email"])
            # Early, unlocked check: finalize checks the caps again under lock.
            # Refusing now spares the depositor an upload that would fail.
            deposits.check_caps(target=target, depositor_email=data["depositor_email"])
        except deposits.CapReached as exc:
            raise drf.exceptions.Throttled(detail=exc.detail) from exc

        challenge, code = deposits.create_challenge(
            space=space,
            inbox_email=data.get("recipient_email", ""),
            depositor_email=data["depositor_email"],
            depositor_name=data["depositor_name"],
            ip=request.META.get("REMOTE_ADDR"),
        )
        try:
            send_deposit_otp(challenge, code)
        except Exception:
            logger.exception("Failed to send deposit code for %s", challenge.id)
            challenge.delete()
            return Response(
                {"detail": "The code could not be sent. Try again shortly."},
                status=503,
            )
        return Response(
            {"challenge_id": str(challenge.id), "expires_at": challenge.expires_at},
            status=201,
        )


class DepositVerifyView(APIView):
    """POST /deposit-challenges/<id>/verify/: trade the code for an upload
    session token."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [DepositVerifyThrottle]

    @extend_schema(request=DepositVerifySerializer)
    def post(self, request, challenge_id):
        serializer = DepositVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result, challenge = deposits.verify_code(
            challenge_id, serializer.validated_data["code"]
        )
        if result == "not_found":
            return Response({"detail": "Unknown code request."}, status=404)
        if result == "wrong" and deposits.attempts_left(challenge):
            return Response(
                {
                    "code": "This code is not right.",
                    "reason": "wrong_code",
                    "attempts_left": deposits.attempts_left(challenge),
                },
                status=400,
            )
        if result != "ok":
            return Response(
                {
                    "detail": "This code has expired. Ask for a new one.",
                    "reason": "expired",
                },
                status=410,
            )
        return Response(
            {
                "deposit_token": deposits.sign_session(challenge),
                "expires_at": timezone.now()
                + timedelta(seconds=settings.DEPOSIT_SESSION_MAX_AGE),
            }
        )


class DepositDraftViewSet(TransferDraftViewSet):
    """The draft upload actions of ``/drafts/``, for a depositor's session.

    The draft belongs to the challenge, not to a user, and one challenge
    holds one draft. Finalize creates an inbound transfer for the space's
    owner or, for an anonymous send, for whoever the address resolves to.
    """

    authentication_classes = []
    permission_classes = [DepositCapabilityPermission]

    def get_queryset(self):
        return models.TransferDraft.objects.filter(
            deposit_challenge=self.request.deposit_challenge
        )

    def get_serializer_class(self):
        if self.action == "add_file":
            return DepositAddFileSerializer
        if self.action == "finalize":
            return DepositFinalizeSerializer
        return super().get_serializer_class()

    def _new_draft(self, request):
        # The unique constraint settles parallel first drops.
        try:
            with transaction.atomic():
                return models.TransferDraft.objects.create(
                    deposit_challenge=request.deposit_challenge,
                    encryption_chunk_size=settings.TRANSFER_CHUNK_SIZE,
                )
        except (IntegrityError, DjangoValidationError) as exc:
            raise drf.exceptions.ValidationError(
                {
                    "draft_id": "This deposit session already has a draft: "
                    "send its draft_id."
                }
            ) from exc

    def _deposit_cap(self):
        space = self.request.deposit_challenge.deposit_space
        if space is not None:
            return space.effective_max_deposit_size
        return settings.DEPOSIT_MAX_TOTAL_SIZE

    def _max_file_size(self):
        return min(settings.TRANSFER_MAX_FILE_SIZE, self._deposit_cap())

    def _max_total_size(self):
        return self._deposit_cap()

    @extend_schema(
        request=DepositFinalizeSerializer,
        responses={200: DepositReceiptSerializer},
    )
    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        """Turn the draft into an inbound transfer, through the same 202 poll
        loop as ``/drafts/``. Infected files and scan errors refuse the
        deposit; files exempt from scanning (too large, unscannable, scan
        off) go through, and the agent is warned."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metadata = serializer.validated_data

        with transaction.atomic():
            draft = self._get_locked_draft(pk)
            challenge = models.DepositChallenge.objects.select_for_update().get(
                pk=request.deposit_challenge.pk
            )
            if challenge.consumed_at is not None:
                raise drf.exceptions.PermissionDenied(
                    {"detail": "This deposit was already sent.", "reason": "session"}
                )
            deposits.lock_for_caps(challenge)
            # The target may have closed since the session began. Checked after
            # lock_for_caps, so a revoke cannot land before the deposit is saved.
            if not deposits.target_open(challenge):
                raise drf.exceptions.PermissionDenied(deposits_closed_body())
            try:
                deposits.check_caps(
                    target=deposits.target_key(
                        challenge.deposit_space_id, challenge.inbox_email
                    ),
                    depositor_email=challenge.depositor_email,
                )
            except deposits.CapReached as exc:
                raise drf.exceptions.Throttled(detail=exc.detail) from exc

            files = list(draft.files.all())
            self._reject_bad_finalize_shape(files, [], files, False)
            self._reject_key_change(draft, metadata, False)
            self._park_encryption_key(draft, metadata, False)
            self._submit_pending_scans(draft, files, False)
            scan_response = self._scan_gate(files)
            if scan_response is not None:
                return scan_response

            transfer = self._create_deposit(draft, challenge, metadata, request)

        prefetch_related_objects([transfer], "files")
        return Response(DepositReceiptSerializer(transfer).data)

    def _create_deposit(self, draft, challenge, metadata, request):
        space = challenge.deposit_space
        if space is not None:
            owner = space.owner
            retention_days = space.retention_days
        else:
            owner = deposits.resolve_inbox_owner(challenge.inbox_email)
            retention_days = settings.INBOX_RETENTION_DAYS
        transfer = models.Transfer.objects.create(
            owner=owner,
            title=metadata["title"],
            direction=TransferDirection.INBOUND,
            sharing_mode=SharingMode.LINK,
            expires_at=timezone.now() + timedelta(days=retention_days),
            encryption_key=draft.encryption_key,
            encryption_chunk_size=draft.encryption_chunk_size,
            deposit_space=space,
            inbox_email=challenge.inbox_email,
            depositor_name=challenge.depositor_name,
            depositor_email=challenge.depositor_email,
        )
        self._reparent_files(draft, transfer)
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at", "updated_at"])

        files = list(transfer.files.all())
        # The deposit caps count these.
        models.TransferEvent.objects.create(
            transfer_id=transfer.id,
            event_type=TransferEventType.DEPOSIT_RECEIVED,
            actor_type=ActorType.EXTERNAL,
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            payload={
                "target": deposits.target_key(
                    challenge.deposit_space_id, challenge.inbox_email
                ),
                "depositor_email": challenge.depositor_email,
                # The depositor's title, kept once the agent renames it.
                "title": transfer.title,
                "file_count": len(files),
                "size": sum(f.plaintext_size or f.size for f in files),
            },
        )

        transfer_id = str(transfer.id)
        transaction.on_commit(lambda: send_deposit_notification_task.send(transfer_id))
        transaction.on_commit(lambda: send_deposit_receipt_task.send(transfer_id))

        draft.delete()
        return transfer


class InboxClaimView(APIView):
    """POST /inbox/claim/: attach an anonymous send to the signed-in agent.

    Needs both the signed link mailed to the address and a session whose
    identity email is that address: the link alone could be forwarded, the
    email alone could be asserted by any identity provider. A successful
    claim records that this agent reads the mailbox, so later sends to it
    attach at once, and takes every other unclaimed send to it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=InboxClaimSerializer)
    def post(self, request):
        serializer = InboxClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer_id = deposits.load_claim(serializer.validated_data["token"])
        if transfer_id is None:
            return Response(
                {"detail": "This link is not valid.", "reason": "invalid"}, status=400
            )
        user = request.user
        email = deposits.normalize_email(user.email)
        with transaction.atomic():
            # Taken before any row lock: two claims by the same agent cannot
            # deadlock, and a deposit finalized meanwhile is either claimed
            # here or attached at once by resolve_inbox_owner.
            deposits.lock_inbox(email)
            transfer = (
                models.Transfer.objects.select_for_update()
                .filter(id=transfer_id, direction=TransferDirection.INBOUND)
                .first()
            )
            if transfer is None or (
                transfer.owner_id is not None and transfer.owner_id != user.id
            ):
                return Response(
                    {"detail": "Nothing to collect here.", "reason": "not_found"},
                    status=404,
                )
            if transfer.owner_id == user.id:
                return Response({"id": str(transfer.id)})
            if not email or email != transfer.inbox_email:
                return Response(
                    {
                        "detail": "This deposit was sent to another address.",
                        "reason": "wrong_account",
                    },
                    status=403,
                )
            if transfer.status != TransferStatus.ACTIVE or transfer.is_expired:
                return Response(
                    {"detail": "This deposit has expired.", "reason": "expired"},
                    status=410,
                )

            claimed = list(
                models.Transfer.objects.select_for_update().filter(
                    direction=TransferDirection.INBOUND,
                    owner__isnull=True,
                    inbox_email=email,
                    status=TransferStatus.ACTIVE,
                    expires_at__gt=timezone.now(),
                )
            )
            models.Transfer.objects.filter(id__in=[t.id for t in claimed]).update(
                owner=user, updated_at=timezone.now()
            )
            models.User.objects.filter(id=user.id).update(inbox_claimed_email=email)
            for claimed_transfer in claimed:
                log_agent_event(
                    claimed_transfer, TransferEventType.INBOUND_CLAIMED, request
                )
        return Response({"id": str(transfer.id)})
