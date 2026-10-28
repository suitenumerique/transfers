"""Deposits: files sent to an agent by someone without an account.

They go through a deposit space's link, or straight to an agent's email
(an inbox send, allowed by ``INBOX_RECIPIENT_EMAIL_REGEX``). Either way the
depositor proves their email with a one-time code, which opens a signed
upload session, and the deposit becomes an inbound ``Transfer``.
"""

import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import connection
from django.db.models import F, Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from core import models
from core.enums import TransferEventType

# Signing namespaces (Django's ``salt``): a token signed for one use is
# refused by the other.
SESSION_SALT = "deposit-session"
CLAIM_SALT = "inbox-claim"


class CapReached(Exception):
    """A deposit cap is full. ``detail`` says which."""

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def inbox_enabled() -> bool:
    return bool(settings.INBOX_RECIPIENT_EMAIL_REGEX)


def inbox_email_allowed(email: str) -> bool:
    """Whether an anonymous send may target this address. The whole address
    must match, so a pattern for a domain cannot be met by a prefix."""
    pattern = settings.INBOX_RECIPIENT_EMAIL_REGEX
    if not pattern:
        return False
    return re.fullmatch(pattern, normalize_email(email), re.IGNORECASE) is not None


# -- One-time code --


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def _code_hash(challenge_id, code: str) -> str:
    return salted_hmac(
        "deposit-otp", f"{challenge_id}:{code}", algorithm="sha256"
    ).hexdigest()


def create_challenge(*, space, inbox_email, depositor_email, depositor_name, ip):
    """Create a challenge and return it with its code, which is only ever
    emailed: the database keeps a keyed hash."""
    code = new_code()
    challenge = models.DepositChallenge(
        deposit_space=space,
        inbox_email=normalize_email(inbox_email) if space is None else "",
        depositor_email=normalize_email(depositor_email),
        depositor_name=depositor_name.strip(),
        expires_at=timezone.now() + timedelta(seconds=settings.DEPOSIT_OTP_TTL_SECONDS),
        ip=ip,
    )
    challenge.code_hash = _code_hash(challenge.id, code)
    challenge.save()
    return challenge, code


def verify_code(challenge_id, code: str):
    """Spend one try on ``challenge_id``. Returns ``(status, challenge)``,
    status one of ``ok``, ``wrong``, ``expired``, ``not_found``.

    The try is taken by a conditional UPDATE before comparing, so parallel
    guesses cannot share one."""
    now = timezone.now()
    taken = models.DepositChallenge.objects.filter(
        id=challenge_id,
        verified_at__isnull=True,
        expires_at__gt=now,
        attempts__lt=settings.DEPOSIT_OTP_MAX_ATTEMPTS,
    ).update(attempts=F("attempts") + 1, updated_at=now)
    challenge = models.DepositChallenge.objects.filter(id=challenge_id).first()
    if challenge is None:
        return "not_found", None
    if not taken:
        return "expired", challenge
    if not constant_time_compare(challenge.code_hash, _code_hash(challenge.id, code)):
        return "wrong", challenge
    # Only one request can stamp it, even with the right code twice.
    stamped = models.DepositChallenge.objects.filter(
        id=challenge.id, verified_at__isnull=True
    ).update(verified_at=now, updated_at=now)
    if not stamped:
        return "expired", challenge
    challenge.verified_at = now
    return "ok", challenge


def attempts_left(challenge) -> int:
    return max(0, settings.DEPOSIT_OTP_MAX_ATTEMPTS - challenge.attempts)


# -- Upload session --


def sign_session(challenge) -> str:
    return signing.TimestampSigner(salt=SESSION_SALT).sign(str(challenge.id))


def load_session(token: str):
    """The verified, unconsumed challenge behind a session token, or None."""
    if not token:
        return None
    try:
        challenge_id = signing.TimestampSigner(salt=SESSION_SALT).unsign(
            token, max_age=settings.DEPOSIT_SESSION_MAX_AGE
        )
    except signing.BadSignature:
        return None
    return (
        models.DepositChallenge.objects.select_related("deposit_space__owner")
        .filter(id=challenge_id, verified_at__isnull=False, consumed_at__isnull=True)
        .first()
    )


def target_open(challenge) -> bool:
    """Whether the challenge's target still accepts deposits."""
    if challenge.deposit_space_id is not None:
        return challenge.deposit_space.is_open
    return inbox_email_allowed(challenge.inbox_email)


# -- Caps --


def target_key(space_id, inbox_email: str) -> str:
    """The recipient the deposit caps count by: a space, or an address."""
    if space_id is not None:
        return f"space:{space_id}"
    return f"email:{normalize_email(inbox_email)}"


def _advisory_lock(key: str):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [key])


def lock_inbox(email: str):
    """Serialize deposits to one inbox address and claims of it until the
    transaction ends."""
    _advisory_lock(target_key(None, email))


def lock_for_caps(challenge):
    """Serialize deposits on one target, then on one depositor, until the
    transaction ends, so two finalizes cannot both pass a cap check. Always
    in this order: target first, depositor second."""
    if challenge.deposit_space_id is not None:
        models.DepositSpace.objects.select_for_update().get(
            pk=challenge.deposit_space_id
        )
    else:
        lock_inbox(challenge.inbox_email)
    _advisory_lock(f"depositor:{challenge.depositor_email}")


def _deposits_since(filters: Q, period_seconds: int) -> int:
    since = timezone.now() - timedelta(seconds=period_seconds)
    return models.TransferEvent.objects.filter(
        filters,
        event_type=TransferEventType.DEPOSIT_RECEIVED,
        created_at__gte=since,
    ).count()


def challenge_retention() -> timedelta:
    """How long a challenge row is kept: past its upload session, and past
    the THROTTLE_DEPOSIT_CODES_PER_EMAIL window, which counts these rows.
    Plus an hour of margin."""
    seconds = settings.DEPOSIT_SESSION_MAX_AGE
    rate = settings.THROTTLE_DEPOSIT_CODES_PER_EMAIL
    if rate:
        seconds = max(seconds, rate[2])
    return timedelta(seconds=seconds + 3600)


def check_code_requests(depositor_email: str):
    """Raise ``CapReached`` past THROTTLE_DEPOSIT_CODES_PER_EMAIL codes sent
    to one address: each code allows a few guesses, so this bounds how
    long someone can try to pass as that address."""
    rate = settings.THROTTLE_DEPOSIT_CODES_PER_EMAIL
    if not rate:
        return
    limit, period_name, period_seconds = rate
    since = timezone.now() - timedelta(seconds=period_seconds)
    sent = models.DepositChallenge.objects.filter(
        depositor_email=normalize_email(depositor_email), created_at__gte=since
    ).count()
    if sent >= limit:
        raise CapReached(
            f"No more than {limit} codes can be sent to one address per {period_name}."
        )


def check_caps(*, target: str, depositor_email: str):
    """Raise ``CapReached`` when the target or the depositor has had its
    share of deposits over the window. Counted from DEPOSIT_RECEIVED events,
    which outlive the transfers."""
    rate = settings.THROTTLE_DEPOSITS_PER_TARGET
    if rate:
        limit, period_name, period_seconds = rate
        if _deposits_since(Q(payload__target=target), period_seconds) >= limit:
            raise CapReached(
                f"This recipient cannot receive more than {limit} deposits "
                f"per {period_name}."
            )
    rate = settings.THROTTLE_DEPOSITS_PER_DEPOSITOR
    if rate:
        limit, period_name, period_seconds = rate
        filters = Q(payload__depositor_email=normalize_email(depositor_email))
        if _deposits_since(filters, period_seconds) >= limit:
            raise CapReached(
                f"You cannot make more than {limit} deposits per {period_name}."
            )


# -- Inbox sends: who an anonymous send belongs to --


def resolve_inbox_owner(email: str):
    """The agent an anonymous send to ``email`` attaches to at once, or None
    until claimed. Only someone who already proved they read that mailbox
    by claiming a send to it, and only when that is unambiguous: matching
    the identity email alone would hand the send to whichever provider
    first asserts the address."""
    email = normalize_email(email)
    candidates = list(
        models.User.objects.filter(
            is_active=True,
            email__iexact=email,
            inbox_claimed_email__iexact=email,
        )[:2]
    )
    return candidates[0] if len(candidates) == 1 else None


def sign_claim(transfer) -> str:
    return signing.TimestampSigner(salt=CLAIM_SALT).sign(str(transfer.id))


def load_claim(token: str):
    """The transfer id a claim token names, or None. Valid as long as an
    anonymous send is kept."""
    if not token:
        return None
    try:
        return signing.TimestampSigner(salt=CLAIM_SALT).unsign(
            token, max_age=timedelta(days=settings.INBOX_RETENTION_DAYS + 1)
        )
    except signing.BadSignature:
        return None
