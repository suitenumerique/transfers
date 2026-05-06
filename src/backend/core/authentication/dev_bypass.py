"""Dev-only OIDC bypass so end-to-end work can proceed without ProConnect.

Gated on ``settings.DEV_AUTH_BYPASS`` — the URL itself isn't mounted unless
the flag is on, and the view also rechecks the flag defensively in case
settings land on a production-shaped deployment by mistake. Never import
this from anywhere that isn't the dev URL wiring.
"""

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import Http404, HttpResponseRedirect
from django.views.generic import View

_DEFAULT_BYPASS_EMAIL = "dev@transferts.local"
_DEV_CLAIMS_SESSION_KEY = "dev_oidc_claims"


class DevLoginView(View):
    """GET /dev-login/?email=foo@bar.tld&next=/  → set a session cookie.

    Creates (or reuses) a user with the given email and a ``sub`` prefixed
    with ``dev:`` so it can't collide with real OIDC subs. The Django
    session cookie ``transferts_sessionid`` then travels with every
    subsequent API call via ``credentials: "include"``.
    """

    def get(self, request):
        if not getattr(settings, "DEV_AUTH_BYPASS", False):
            raise Http404

        email = request.GET.get("email", _DEFAULT_BYPASS_EMAIL).strip().lower()
        next_url = request.GET.get("next", "/")

        user_model = get_user_model()
        try:
            user = user_model.objects.get(email=email)
        except user_model.DoesNotExist:
            user = user_model(
                email=email,
                sub=f"dev:{email}",
                full_name=email.split("@")[0].replace(".", " ").title(),
            )
            # The model's ``full_clean`` hook in ``save`` rejects a blank
            # password; set_unusable_password leaves a sentinel that
            # ``check_password`` always rejects, which is what we want —
            # the bypass is the only way to log this user in.
            user.set_unusable_password()
            user.save()

        # Explicit backend because AUTHENTICATION_BACKENDS ships two
        # (ModelBackend + OIDCAuthenticationBackend) — Django refuses to
        # guess when more than one is configured.
        login(
            request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        # Persist minimal OIDC-like claims in the session so downstream
        # services (e.g. entitlements) that expect `request.user.claims`
        # can work during dev-bypass flows.
        oidc_claims = (
            getattr(settings, "ENTITLEMENTS_BACKEND_PARAMETERS", {}).get("oidc_claims", [])
            or []
        )
        claims = {}
        for claim in oidc_claims:
            raw_value = request.GET.get(claim)
            if raw_value is not None and str(raw_value).strip() != "":
                claims[claim] = raw_value
        request.session[_DEV_CLAIMS_SESSION_KEY] = claims
        return HttpResponseRedirect(next_url)
