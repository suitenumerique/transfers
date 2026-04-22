"""Authentication URLs for the transferts core app."""

from django.conf import settings
from django.urls import include, path

from core.authentication.dev_bypass import DevLoginView

urlpatterns = [
    path("", include("lasuite.oidc_login.urls")),
]

# Dev-only session bootstrapper — mounted only when the flag is on so it
# never ships with prod-shaped deployments. The view also rechecks the
# flag at request time as a second line of defense.
if getattr(settings, "DEV_AUTH_BYPASS", False):
    urlpatterns.append(path("dev-login/", DevLoginView.as_view(), name="dev-login"))
