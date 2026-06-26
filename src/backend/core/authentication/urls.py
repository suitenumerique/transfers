"""Authentication URLs for the transferts core app."""

from django.urls import include, path

urlpatterns = [
    path("", include("lasuite.oidc_login.urls")),
]
