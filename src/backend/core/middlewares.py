"""Custom middleware for the transferts application."""


class XForwardedForMiddleware:
    """Middleware that sets REMOTE_ADDR from the X-Forwarded-For header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            real_ip = request.META["HTTP_X_FORWARDED_FOR"]
        except KeyError:
            pass
        else:
            real_ip = real_ip.split(",")[0].strip()
            request.META["REMOTE_ADDR"] = real_ip

        return self.get_response(request)
