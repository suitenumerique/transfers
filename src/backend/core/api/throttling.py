"""Rate limits on the endpoints worth abusing.

Each class is a scope whose rate lives in ``REST_FRAMEWORK
["DEFAULT_THROTTLE_RATES"]`` (env-tunable). ``UserRateThrottle`` keys an
authenticated caller on their user id and anyone else on their IP.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from core.services import deposits


class DraftAddFileThrottle(UserRateThrottle):
    """Attaching files: bounds storage churn and server-side Drive fetches."""

    scope = "draft_add_file"


class TransferResendThrottle(UserRateThrottle):
    """Re-sending invitation emails."""

    scope = "transfer_resend"


class PublicDownloadThrottle(UserRateThrottle):
    """The public download page and file URLs, keyed per IP for visitors.
    Generous: one agency behind a single NAT may fetch many files."""

    scope = "public_download"


class _PerIPThrottle(SimpleRateThrottle):
    """Keyed on the caller's IP, logged in or not: the deposit endpoints run
    without authentication."""

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class DepositChallengeThrottle(_PerIPThrottle):
    """Asking for a depositor's one-time code."""

    scope = "deposit_challenge"


class DepositChallengeEmailThrottle(SimpleRateThrottle):
    """Asking for a code for one depositor email, from any IP: bounds the
    mail one address can be sent."""

    scope = "deposit_challenge_email"

    def get_cache_key(self, request, view):
        data = request.data if isinstance(request.data, dict) else {}
        email = data.get("depositor_email")
        if not isinstance(email, str) or not email.strip():
            return None
        email = deposits.normalize_email(email)
        digest = hashlib.sha256(email.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class DepositVerifyThrottle(_PerIPThrottle):
    """Code guesses."""

    scope = "deposit_verify"


class DepositPublicThrottle(_PerIPThrottle):
    """The public page of a deposit space."""

    scope = "deposit_public"
