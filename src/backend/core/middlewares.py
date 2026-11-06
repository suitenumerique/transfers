"""Custom middleware for the transfers application."""


class XForwardedForMiddleware:
    """Middleware that sets REMOTE_ADDR from the X-Forwarded-For header.

    Reads the *rightmost* entry, never the leftmost: a client can send its
    own ``X-Forwarded-For``, and a proxy that appends rather than
    overwrites leaves that forged prefix in place. The last entry is the
    one the closest trusted hop wrote.

    In this deployment that hop is Caddy, which sets the header to the
    single address it established from its own ``trusted_proxies_strict``
    walk (see ``src/frontend/caddy/Caddyfile``), so the rightmost entry is
    the only entry. Any other topology has to put a hop in front that
    appends or replaces the header, or ``REMOTE_ADDR`` becomes whatever a
    client chose to send — and here that address keys DRF's anonymous
    throttles (``NUM_PROXIES = 0``) and is what the audit log records.

    The admin IP allowlist is not enforced here: Caddy answers 403 on
    ``DJANGO_ADMIN_IP_ALLOWLIST`` using its own ``client_ip``, before the
    request is ever proxied. Django never checks it, so exposing this
    backend directly — without Caddy in front — serves the admin to every
    client, whatever the allowlist says.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            real_ip = request.META["HTTP_X_FORWARDED_FOR"]
        except KeyError:
            pass
        else:
            real_ip = real_ip.split(",")[-1].strip()
            request.META["REMOTE_ADDR"] = real_ip

        return self.get_response(request)
