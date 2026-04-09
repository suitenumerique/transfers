"""URL configuration for the core app."""

from django.conf import settings
from django.urls import include, path

from rest_framework.routers import DefaultRouter

from core.api.viewsets.config import ConfigView
from core.api.viewsets.download import DownloadFileView, DownloadTransferView
from core.api.viewsets.transfer import TransferViewSet
from core.api.viewsets.user import UserViewSet
from core.authentication.urls import urlpatterns as oidc_urls

router = DefaultRouter()
router.register("users", UserViewSet, basename="users")
router.register("transfers", TransferViewSet, basename="transfers")

urlpatterns = [
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
            ]
        ),
    ),
    path(f"api/{settings.API_VERSION}/config/", ConfigView.as_view()),
    # Public download endpoints (no auth)
    path(
        f"api/{settings.API_VERSION}/downloads/<str:public_token>/",
        DownloadTransferView.as_view(),
        name="download-transfer",
    ),
    path(
        f"api/{settings.API_VERSION}/downloads/<str:public_token>/files/<uuid:file_id>/download/",
        DownloadFileView.as_view(),
        name="download-file",
    ),
]
