"""Rate limits on the endpoints worth abusing.

Each class is a scope whose rate lives in ``REST_FRAMEWORK
["DEFAULT_THROTTLE_RATES"]`` (env-tunable). ``UserRateThrottle`` keys an
authenticated caller on their user id and anyone else on their IP.
"""

from rest_framework.throttling import UserRateThrottle


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
