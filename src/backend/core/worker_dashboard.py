"""Mount the task-queue (worker) dashboard inside the Django admin.

The dashboard is provided by the ``dramatiq-redis-streams`` broker. It ships
destructive endpoints (flush / purge / requeue) and serves task payloads, with
no authentication of its own. We therefore wrap it in ``admin.site.admin_view``
— so it lives behind the ordinary admin login and its redirect flow — and, on
top of that, require ``is_superuser``: ``admin_view`` alone only checks
``is_staff``, which is too broad for destructive queue control, so a staff user
who is not a superuser gets a 403.

It stays ``csrf_exempt`` because its fetch()-based POST actions carry no CSRF
token; those POSTs are protected instead by ``SESSION_COOKIE_SAMESITE`` (pinned
to ``"Lax"`` in settings), which stops the admin session cookie from riding
along on a cross-site request, plus the superuser check above.
"""

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import re_path
from django.views.decorators.csrf import csrf_exempt

from dramatiq_redis_streams import StreamsBroker
from dramatiq_redis_streams.dashboard import DashboardApp


def _dashboard_broker():
    """Build a read-only ``StreamsBroker`` for the dashboard.

    ``middleware=[]`` keeps it from running any task middleware, and the Redis
    connection is lazy (redis-py connects on first command), so constructing
    this at URL-import time is safe even when Redis is unreachable.
    """
    return StreamsBroker(
        middleware=[],
        url=settings.WORKER_BROKER_URL,
        namespace=settings.WORKER_QUEUE_NAMESPACE,
    )


def dashboard_urlpatterns(prefix):
    """Return URL patterns mounting the dashboard behind the admin staff login.

    ``prefix`` is the full path the dashboard is mounted at (e.g.
    ``"admin/worker-dashboard"``); the WSGI app strips it from ``PATH_INFO`` so
    its own relative routes resolve.
    """
    wsgi_app = DashboardApp(_dashboard_broker(), prefix=prefix)

    # ``path`` is captured by the route regex (Django passes it as a kwarg) but
    # unused: the WSGI app reads the full request.path instead.
    def _view(request, path=""):  # pylint: disable=unused-argument
        # admin_view (below) has already guaranteed an authenticated, active
        # staff user; require superuser on top since the dashboard exposes
        # destructive queue actions and task payloads.
        if not request.user.is_superuser:
            raise PermissionDenied

        # Bridge Django's request into a one-shot WSGI call.
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

    # csrf_exempt must be the OUTERMOST wrapper so CsrfViewMiddleware sees it on
    # the resolved view and skips the CSRF check; admin_view (inside) enforces the
    # admin login and redirects anonymous users to it, and _view itself requires
    # is_superuser.
    guarded = csrf_exempt(admin.site.admin_view(_view))

    prefix_stripped = prefix.strip("/")
    if prefix_stripped:
        prefix_stripped += "/"

    return [
        re_path(
            rf"^{prefix_stripped}(?P<path>.*)$",
            guarded,
            name="worker-dashboard",
        ),
    ]
