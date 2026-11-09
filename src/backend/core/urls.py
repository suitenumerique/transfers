"""URL configuration for the core app."""

from django.conf import settings
from django.urls import include, path

from rest_framework.routers import DefaultRouter

from core.api.viewsets.config import ConfigView
from core.api.viewsets.deposit import (
    DepositChallengeView,
    DepositDraftViewSet,
    DepositSpaceViewSet,
    DepositVerifyView,
    InboxClaimView,
    PublicDepositSpaceView,
)
from core.api.viewsets.download import DownloadFileView, DownloadTransferView
from core.api.viewsets.draft import TransferDraftViewSet
from core.api.viewsets.transfer import TransferViewSet
from core.api.viewsets.user import UserViewSet
from core.api.viewsets.webhook import ScanResultWebhookView
from core.authentication.urls import urlpatterns as oidc_urls

router = DefaultRouter()
router.register("users", UserViewSet, basename="users")
router.register("drafts", TransferDraftViewSet, basename="drafts")
router.register("transfers", TransferViewSet, basename="transfers")
router.register("deposit-spaces", DepositSpaceViewSet, basename="deposit-spaces")
router.register("deposit-drafts", DepositDraftViewSet, basename="deposit-drafts")

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
    # Deposits: a space's public page and the depositor's steps, all without
    # authentication. Not under deposit-spaces/, whose router routes take any
    # first segment as a space id.
    path(
        f"api/{settings.API_VERSION}/public-deposit-spaces/<str:link_token>/",
        PublicDepositSpaceView.as_view(),
        name="deposit-space-public",
    ),
    path(
        f"api/{settings.API_VERSION}/deposit-challenges/",
        DepositChallengeView.as_view(),
        name="deposit-challenges",
    ),
    path(
        f"api/{settings.API_VERSION}/deposit-challenges/<uuid:challenge_id>/verify/",
        DepositVerifyView.as_view(),
        name="deposit-challenge-verify",
    ),
    # A signed-in agent collecting an anonymous send.
    path(
        f"api/{settings.API_VERSION}/inbox/claim/",
        InboxClaimView.as_view(),
        name="inbox-claim",
    ),
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
    # Inbound webhook from the clamav file-scanner (no auth — protected by a
    # per-file secret in the query string).
    path(
        f"api/{settings.API_VERSION}/webhooks/scan-result/",
        ScanResultWebhookView.as_view(),
        name="scan-result-webhook",
    ),
]
