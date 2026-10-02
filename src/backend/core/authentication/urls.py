"""Authentication URLs for the transfers core app."""

from django.urls import include, path

urlpatterns = [
    path("", include("lasuite.oidc_login.urls")),
]
