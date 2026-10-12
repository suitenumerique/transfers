"""Outbound HTTP to URLs a user handed us (Drive imports).

The worker fetches these server-side, so a free-form URL would let any agent
make it GET whatever it can reach — cloud metadata, internal services — and
read the answer back as a transfer. Two gates:

* ``is_drive_url``: the URL must point at the configured Drive instance
  (same scheme and host as ``DRIVE_CONFIG["base_url"]``). Checked when the
  file is attached and again before the fetch.
* ``get_public``: redirects are followed by hand, and every hop (Drive's
  permalink typically redirects to object storage) must resolve to public
  addresses only, unless ``DRIVE_IMPORT_ALLOW_PRIVATE_NETWORKS`` is set (dev,
  where Drive and its storage live on the Docker network).

The resolution check runs before ``requests`` resolves the host again, so a
DNS answer that changes in between (rebinding) is not covered; the Drive host
allowlist is what bounds that.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

from django.conf import settings

import requests

MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    """The URL (or a redirect it led to) is not one we may fetch."""


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), (parts.netloc or "").lower()


def is_drive_url(url: str) -> bool:
    """True iff ``url`` lives on the configured Drive instance."""
    base_url = (getattr(settings, "DRIVE_CONFIG", None) or {}).get("base_url")
    if not base_url or not url:
        return False
    scheme, netloc = _origin(url)
    return scheme in ("http", "https") and (scheme, netloc) == _origin(base_url)


def _resolve(host: str, port: int) -> list:
    """Every address ``host`` resolves to."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Cannot resolve {host}.") from exc
    # Drop any IPv6 zone id ("fe80::1%eth0") before parsing.
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


def _check_hop(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURLError("Only http(s) URLs with a host can be fetched.")
    if settings.DRIVE_IMPORT_ALLOW_PRIVATE_NETWORKS:
        return
    port = parts.port or (443 if parts.scheme == "https" else 80)
    for address in _resolve(parts.hostname, port):
        mapped = getattr(address, "ipv4_mapped", None)
        if not address.is_global or (mapped is not None and not mapped.is_global):
            raise UnsafeURLError(
                f"{parts.hostname} resolves to a non-public address ({address})."
            )


def get_public(url: str, *, timeout: float) -> requests.Response:
    """Streamed GET of ``url``, following at most ``MAX_REDIRECTS`` redirects,
    each one checked by ``_check_hop``. The caller owns (and must close) the
    returned response."""
    for _ in range(MAX_REDIRECTS + 1):
        _check_hop(url)
        response = requests.get(
            url, stream=True, timeout=timeout, allow_redirects=False
        )
        if not response.is_redirect:
            return response
        location = response.headers.get("Location", "")
        response.close()
        url = urljoin(url, location)
    raise UnsafeURLError(f"More than {MAX_REDIRECTS} redirects.")
