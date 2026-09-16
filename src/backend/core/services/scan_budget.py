"""How long a scan may take before it counts as lost.

The scanner downloads the file, decrypts it and streams it to clamd, so the
time scales with size. One formula, ``SCAN_WAIT_BASE_SECONDS +
SCAN_WAIT_SECONDS_PER_GIB × size``, shared by the frontend poller (through
/config/), /rescan/ and the reaper, so the three agree on when a pending
scan is "still running" versus "never coming back".
"""

import math

from django.conf import settings

GIB = 1024**3


def scan_wait_seconds(size_bytes: int) -> int:
    per_gib = settings.SCAN_WAIT_SECONDS_PER_GIB
    return settings.SCAN_WAIT_BASE_SECONDS + math.ceil(
        max(size_bytes, 0) / GIB * per_gib
    )
