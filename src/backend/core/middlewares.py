"""Custom middleware for the transferts application."""


class XForwardedForMiddleware:
    """Middleware that sets REMOTE_ADDR from the X-Forwarded-For header.

    Reads the *rightmost* entry, which is the IP appended by our trusted
    edge proxy (Scalingo's router). The leftmost entries can be spoofed by
    a client sending their own ``X-Forwarded-For`` because the router
    appends rather than overwrites.
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
