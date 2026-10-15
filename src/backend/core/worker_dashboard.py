"""Mount the task-queue (worker) dashboard inside the Django admin.

The dashboard comes with the ``dramatiq-redis-streams`` broker. It has
destructive endpoints (flush, remove, requeue) and shows task payloads, with
no authentication of its own. It is therefore wrapped in
``admin.site.admin_view``, so it sits behind the admin login, and restricted
to superusers: ``admin_view`` alone admits any staff user.

Its POST actions are fetch() calls that carry no CSRF token, so Django's
CSRF check is replaced by an ``Origin`` check: a browser always sends that
header on such a request, and another site cannot forge it.
"""

import re

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import re_path
from django.views.decorators.csrf import csrf_exempt

from dramatiq_redis_streams import StreamsBroker
from dramatiq_redis_streams.dashboard import DashboardApp

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _dashboard_broker():
    """A broker for the dashboard only: no task middleware, and a Redis
    connection opened on first use, so building it at URL import is safe
    even when Redis is down."""
    return StreamsBroker(
        middleware=[],
        url=settings.WORKER_BROKER_URL,
        namespace=settings.WORKER_QUEUE_NAMESPACE,
    )


def _same_origin(request):
    """True when the request comes from a page of this very site."""
    return request.headers.get("Origin") == f"{request.scheme}://{request.get_host()}"


def dashboard_urlpatterns(prefix):
    """URL patterns mounting the dashboard at ``prefix`` (e.g.
    ``"admin/worker-dashboard"``), behind the admin login."""
    wsgi_app = DashboardApp(_dashboard_broker(), prefix=prefix)

    # ``path`` is captured by the route but unused: the WSGI app reads the
    # full request path.
    def _view(request, path=""):  # pylint: disable=unused-argument
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.method not in SAFE_METHODS and not _same_origin(request):
            raise PermissionDenied

        # Hand Django's request to the WSGI app as a one-shot call.
        environ = request.META.copy()
        environ["PATH_INFO"] = request.path
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(wsgi_app(environ, start_response))
        response = HttpResponse(body, status=int(captured["status"].split(" ", 1)[0]))
        for header, value in captured["headers"]:
            response[header] = value
        return response

    # Exempt inside too, or admin_view adds its own csrf_protect; outside, so
    # the CSRF middleware sees it. admin_view sends anonymous users to the
    # admin login.
    guarded = csrf_exempt(admin.site.admin_view(csrf_exempt(_view)))

    prefix_stripped = prefix.strip("/")
    if prefix_stripped:
        prefix_stripped += "/"
    return [
        re_path(
            rf"^{re.escape(prefix_stripped)}(?P<path>.*)$",
            guarded,
            name="worker-dashboard",
        ),
    ]
