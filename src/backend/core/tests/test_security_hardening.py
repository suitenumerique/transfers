"""Regression tests for the security review fixes: bearer tokens, Drive
import SSRF, throttles and quotas, audit events, admin exposure, webhook
secret handling."""

import base64
import ipaddress
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest

from core import models
from core.api.throttling import (
    DraftAddFileThrottle,
    PublicDownloadThrottle,
    TransferResendThrottle,
)
from core.enums import (
    ActorType,
    ScanStatus,
    SharingMode,
    TransferEventType,
    TransferStatus,
)
from core.factories import (
    TransferDraftFactory,
    TransferFactory,
    TransferFileFactory,
    UserFactory,
)
from core.services import safe_http
from core.utils import ThrottleRateValue

API = "/api/v1.0"
# Settings hold the parsed rate; tests build it the same way.
RATE = ThrottleRateValue().to_python
KEY = base64.urlsafe_b64encode(b"\x01" * 32).rstrip(b"=").decode()


def _resolving_to(*addresses):
    return patch(
        "core.services.safe_http._resolve",
        return_value=[ipaddress.ip_address(a) for a in addresses],
    )


# -- Bearer tokens -------------------------------------------------------


@pytest.mark.django_db
def test_bearer_token_is_not_an_authentication_method(api_client):
    """A ProConnect access token minted for another service must not log
    anyone in here: the userinfo endpoint is never even consulted."""
    UserFactory(sub="victim")
    with patch("requests.get") as userinfo:
        response = api_client.get(
            f"{API}/users/me/", HTTP_AUTHORIZATION="Bearer foreign-token"
        )
    assert response.status_code == 401
    userinfo.assert_not_called()


# -- Drive import SSRF ----------------------------------------------------


class TestIsDriveUrl:
    def test_same_origin_accepted(self):
        assert safe_http.is_drive_url("https://drive.example.com/items/1/")

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com/items/1/",
            "http://drive.example.com/items/1/",  # scheme differs
            "https://drive.example.com:8443/items/1/",  # port differs
            "https://drive.example.com.evil.net/",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "",
        ],
    )
    def test_other_origins_rejected(self, url):
        assert not safe_http.is_drive_url(url)

    def test_nothing_accepted_when_drive_is_off(self, settings):
        settings.DRIVE_CONFIG = {**settings.DRIVE_CONFIG, "base_url": ""}
        assert not safe_http.is_drive_url("https://drive.example.com/items/1/")


class TestGetPublic:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "10.0.0.5",
            "172.17.0.2",
            "192.168.1.1",
            "169.254.169.254",
            "::1",
            "fd00::1",
            "::ffff:127.0.0.1",
            "0.0.0.0",
        ],
    )
    def test_non_public_address_refused_before_any_request(self, address):
        with _resolving_to(address), patch("requests.get") as get:
            with pytest.raises(safe_http.UnsafeURLError):
                safe_http.get_public("https://drive.example.com/x", timeout=1)
        get.assert_not_called()

    def test_private_networks_allowed_when_opted_in(self, settings):
        settings.DRIVE_IMPORT_ALLOW_PRIVATE_NETWORKS = True
        final = MagicMock(is_redirect=False)
        with _resolving_to("10.0.0.5"), patch("requests.get", return_value=final):
            assert safe_http.get_public("http://drive.local/x", timeout=1) is final

    def test_redirect_to_internal_address_refused(self):
        hop = MagicMock(is_redirect=True, headers={"Location": "http://metadata/"})

        def resolve(host, port):
            ip = "93.184.215.14" if host == "drive.example.com" else "169.254.169.254"
            return [ipaddress.ip_address(ip)]

        with (
            patch("core.services.safe_http._resolve", side_effect=resolve),
            patch("requests.get", return_value=hop) as get,
        ):
            with pytest.raises(safe_http.UnsafeURLError):
                safe_http.get_public("https://drive.example.com/x", timeout=1)
        # Only the first, public hop was fetched; redirects are never
        # followed by requests itself.
        get.assert_called_once()
        assert get.call_args.kwargs["allow_redirects"] is False
        hop.close.assert_called_once()

    def test_public_redirect_followed(self):
        hop = MagicMock(
            is_redirect=True, headers={"Location": "https://s3.example.net/o"}
        )
        final = MagicMock(is_redirect=False)
        with (
            _resolving_to("93.184.215.14"),
            patch("requests.get", side_effect=[hop, final]) as get,
        ):
            assert (
                safe_http.get_public("https://drive.example.com/x", timeout=1) is final
            )
        assert get.call_args_list[1].args[0] == "https://s3.example.net/o"

    def test_redirect_loop_bounded(self):
        hop = MagicMock(is_redirect=True, headers={"Location": "/again"})
        with _resolving_to("93.184.215.14"), patch("requests.get", return_value=hop):
            with pytest.raises(safe_http.UnsafeURLError):
                safe_http.get_public("https://drive.example.com/x", timeout=1)


@pytest.mark.django_db
class TestAddFileSourceUrl:
    def _add(self, client, source_url):
        return client.post(
            f"{API}/drafts/add-file/",
            {
                "filename": "a.bin",
                "size": 100 + 28,
                "plaintext_size": 100,
                "source_url": source_url,
            },
            format="json",
        )

    def test_foreign_host_rejected(self, authenticated_client):
        response = self._add(authenticated_client, "http://169.254.169.254/latest/")
        assert response.status_code == 400
        assert "source_url" in response.data
        assert not models.TransferFile.objects.exists()

    def test_rejected_when_drive_is_off(self, authenticated_client, settings):
        settings.DRIVE_CONFIG = {**settings.DRIVE_CONFIG, "base_url": ""}
        response = self._add(authenticated_client, "https://drive.example.com/x")
        assert response.status_code == 400

    def test_drive_host_accepted(self, authenticated_client):
        response = self._add(authenticated_client, "https://drive.example.com/x")
        assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_import_task_refuses_a_url_off_the_drive_host(user):
    """A row that predates the check (or a Drive host since changed) is
    never fetched: the import fails instead."""
    from core.tasks import import_drive_file_task

    draft = TransferDraftFactory(
        owner=user, encryption_chunk_size=1024, encryption_key=KEY
    )
    tf = models.TransferFile.objects.create(
        draft=draft,
        filename="x",
        size=128,
        plaintext_size=100,
        s3_key="transfers/x",
        source_url="http://169.254.169.254/latest/meta-data/",
    )
    with patch("requests.get") as get, patch("core.tasks.s3"):
        import_drive_file_task(str(tf.id))
    get.assert_not_called()
    tf.refresh_from_db()
    assert tf.import_failed_at is not None
    assert tf.upload_completed_at is None


# -- Throttles and quotas -----------------------------------------------------


@pytest.mark.django_db
def test_add_file_is_throttled(authenticated_client, patched_s3, monkeypatch):
    monkeypatch.setattr(DraftAddFileThrottle, "rate", "2/hour", raising=False)
    body = {"filename": "a.bin", "size": 128, "plaintext_size": 100}
    codes = [
        authenticated_client.post(
            f"{API}/drafts/add-file/", body, format="json"
        ).status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 429]


@pytest.mark.django_db
def test_public_download_page_is_throttled(api_client, monkeypatch):
    monkeypatch.setattr(PublicDownloadThrottle, "rate", "2/hour", raising=False)
    transfer = TransferFactory()
    codes = [
        api_client.get(f"{API}/downloads/{transfer.public_token}/").status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


@pytest.mark.django_db
def test_forged_forwarded_for_does_not_dodge_the_throttle(api_client, monkeypatch):
    monkeypatch.setattr(PublicDownloadThrottle, "rate", "2/hour", raising=False)
    transfer = TransferFactory()
    codes = [
        api_client.get(
            f"{API}/downloads/{transfer.public_token}/",
            HTTP_X_FORWARDED_FOR=f"203.0.113.{i}",
        ).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


@pytest.mark.django_db
def test_resend_is_throttled(user, authenticated_client, monkeypatch):
    monkeypatch.setattr(TransferResendThrottle, "rate", "2/hour", raising=False)
    transfer = TransferFactory(owner=user, sharing_mode=SharingMode.EMAIL)
    codes = [
        authenticated_client.post(f"{API}/transfers/{transfer.id}/resend/").status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def _created(owner, recipients):
    """The TRANSFER_CREATED event a finalize logs, which the quota sums."""
    models.TransferEvent.objects.create(
        transfer_id=TransferFactory(owner=owner).id,
        event_type=TransferEventType.TRANSFER_CREATED,
        actor_type=ActorType.AGENT,
        actor_id=owner.id,
        payload={"recipient_count": recipients},
    )


@pytest.mark.django_db
class TestRecipientQuota:
    def _finalizable_draft(self, user):
        draft = TransferDraftFactory(owner=user, encryption_chunk_size=1024)
        TransferFileFactory(
            draft=draft,
            transfer=None,
            upload_completed_at=timezone.now(),
            scan_status=ScanStatus.SKIPPED,
        )
        return draft

    def _finalize(self, client, draft, recipients):
        return client.post(
            f"{API}/drafts/{draft.id}/finalize/",
            {
                "sharing_mode": SharingMode.EMAIL,
                "recipients": recipients,
                "encryption_key": KEY,
            },
            format="json",
        )

    def test_over_quota_refused(self, user, authenticated_client, settings):
        settings.THROTTLE_USER_OUTBOUND_RECIPIENTS = RATE("2/day")
        _created(user, 2)
        draft = self._finalizable_draft(user)

        response = self._finalize(authenticated_client, draft, ["c@example.org"])

        assert response.status_code == 429
        assert models.TransferDraft.objects.filter(id=draft.id).exists()

    def test_within_quota_accepted(self, user, authenticated_client, settings):
        settings.THROTTLE_USER_OUTBOUND_RECIPIENTS = RATE("2/day")
        draft = self._finalizable_draft(user)
        with patch("core.tasks.send_recipient_invitations_task.delay"):
            response = self._finalize(
                authenticated_client, draft, ["a@example.org", "b@example.org"]
            )
        assert response.status_code == 200, response.data

    def test_other_agents_recipients_do_not_count(
        self, user, authenticated_client, settings
    ):
        settings.THROTTLE_USER_OUTBOUND_RECIPIENTS = RATE("1/day")
        _created(UserFactory(), 1)
        draft = self._finalizable_draft(user)
        with patch("core.tasks.send_recipient_invitations_task.delay"):
            response = self._finalize(authenticated_client, draft, ["b@example.org"])
        assert response.status_code == 200, response.data

    def test_deleting_the_transfer_does_not_refund_the_quota(
        self, user, authenticated_client, settings
    ):
        settings.THROTTLE_USER_OUTBOUND_RECIPIENTS = RATE("2/day")
        with patch("core.tasks.send_recipient_invitations_task.delay"):
            response = self._finalize(
                authenticated_client,
                self._finalizable_draft(user),
                ["a@example.org", "b@example.org"],
            )
        assert response.status_code == 200, response.data
        models.Transfer.objects.filter(id=response.data["id"]).update(
            status=TransferStatus.DEACTIVATED
        )
        deleted = authenticated_client.delete(f"{API}/transfers/{response.data['id']}/")
        assert deleted.status_code == 204

        response = self._finalize(
            authenticated_client, self._finalizable_draft(user), ["c@example.org"]
        )

        assert response.status_code == 429

    def test_disabled_quota_accepts_any_count(
        self, user, authenticated_client, settings
    ):
        settings.THROTTLE_USER_OUTBOUND_RECIPIENTS = None
        draft = self._finalizable_draft(user)
        with patch("core.tasks.send_recipient_invitations_task.delay"):
            response = self._finalize(
                authenticated_client, draft, ["a@example.org", "b@example.org"]
            )
        assert response.status_code == 200, response.data


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("200/day", (200, "day", 86400)),
        ("30/Minute", (30, "minute", 60)),
        ("", None),
    ],
)
def test_throttle_rate_value_parses(raw, expected):
    assert ThrottleRateValue().to_python(raw) == expected


def test_throttle_rate_value_parses_its_default():
    value = ThrottleRateValue(
        "200/day", environ_name="TEST_UNSET_THROTTLE_RATE", environ_prefix=None
    )
    assert value == (200, "day", 86400)


def test_recipient_quota_setting_is_parsed(settings):
    assert settings.THROTTLE_USER_OUTBOUND_RECIPIENTS == (200, "day", 86400)


@pytest.mark.parametrize("raw", ["200", "x/day", "10/week"])
def test_throttle_rate_value_rejects_bad_rates(raw):
    with pytest.raises(ValueError):
        ThrottleRateValue().to_python(raw)


# -- Audit events ------------------------------------------------------------


@pytest.mark.django_db
def test_hard_delete_is_journaled_with_its_actor(user, authenticated_client):
    transfer = TransferFactory(owner=user, status=TransferStatus.DEACTIVATED)
    response = authenticated_client.delete(f"{API}/transfers/{transfer.id}/")
    assert response.status_code == 204
    event = models.TransferEvent.objects.get(
        transfer_id=transfer.id, event_type=TransferEventType.TRANSFER_DELETED
    )
    assert event.actor_type == ActorType.AGENT
    assert event.actor_id == user.id


@pytest.mark.django_db
def test_resend_is_journaled(user, authenticated_client):
    transfer = TransferFactory(owner=user, sharing_mode=SharingMode.EMAIL)
    with patch("core.tasks.send_recipient_invitations_task.delay"):
        response = authenticated_client.post(f"{API}/transfers/{transfer.id}/resend/")
    assert response.status_code == 200
    assert models.TransferEvent.objects.filter(
        transfer_id=transfer.id,
        event_type=TransferEventType.INVITATIONS_RESENT,
        actor_id=user.id,
    ).exists()


# -- Admin -------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminExposure:
    @pytest.fixture
    def admin_client(self, client, settings):
        # No collectstatic in tests: the manifest storage would 500 on the
        # admin's stylesheets.
        settings.STORAGES = {
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
        admin = UserFactory(is_staff=True, is_superuser=True)
        client.force_login(admin)
        return client

    def test_transfer_key_cannot_be_edited(self, admin_client):
        transfer = TransferFactory(encryption_key=KEY, encryption_chunk_size=1024)
        page = admin_client.get(f"/admin/core/transfer/{transfer.id}/change/")
        assert page.status_code == 200
        assert 'name="encryption_key"' not in page.content.decode()

    def test_draft_key_cannot_be_edited(self, admin_client):
        draft = TransferDraftFactory(encryption_key=KEY, encryption_chunk_size=1024)
        page = admin_client.get(f"/admin/core/transferdraft/{draft.id}/change/")
        assert page.status_code == 200
        assert 'name="encryption_key"' not in page.content.decode()

    def test_scan_verdict_cannot_be_edited(self, admin_client):
        tf = TransferFileFactory(
            scan_status=ScanStatus.INFECTED, webhook_secret="s3cr3t-value"
        )
        page = admin_client.get(f"/admin/core/transferfile/{tf.id}/change/")
        assert page.status_code == 200
        html = page.content.decode()
        assert 'name="scan_status"' not in html
        assert 'name="scan_report"' not in html
        assert "s3cr3t-value" not in html

    def test_transfer_status_cannot_be_edited(self, admin_client):
        """Reopening a deactivated transfer from the admin would leave no
        event in its history."""
        transfer = TransferFactory()
        page = admin_client.get(f"/admin/core/transfer/{transfer.id}/change/")
        assert page.status_code == 200
        html = page.content.decode()
        for field in (
            "status",
            "deactivation_reason",
            "deactivated_at",
            "pending_deletion_at",
        ):
            assert f'name="{field}"' not in html

    def test_the_sub_cannot_be_edited(self, admin_client):
        """Writing a ``sub`` onto an account is signing in as that person: the
        field a login is matched on must come from the IdP, not from a form.
        Still displayed, so support can read it."""
        user = UserFactory(sub="idp-sub-value")
        page = admin_client.get(f"/admin/core/user/{user.id}/change/")
        assert page.status_code == 200
        html = page.content.decode()
        assert 'name="sub"' not in html
        assert "idp-sub-value" in html


# -- Webhook -----------------------------------------------------------------


@pytest.mark.django_db
def test_webhook_non_ascii_secret_is_a_403_not_a_500(api_client):
    draft = TransferDraftFactory()
    tf = TransferFileFactory(draft=draft, transfer=None, webhook_secret="abc")
    response = api_client.post(
        f"{API}/webhooks/scan-result/?file_id={tf.id}&secret=%C3%A9t%C3%A9",
        {"status": "done", "malware": False},
        format="json",
    )
    assert response.status_code == 403
