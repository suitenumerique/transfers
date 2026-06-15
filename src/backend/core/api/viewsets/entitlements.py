import rest_framework as drf
from rest_framework import viewsets
from core.entitlements import get_entitlements_backend
from .. import permissions

class EntitlementsViewset(viewsets.ViewSet):
    """API View for handling entitlements."""

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        """
        GET /api/v1.0/entitlements/
        """
        entitlements_backend = get_entitlements_backend()
        entitlements = {}
        for method_name in dir(entitlements_backend):
            if method_name.startswith("can_"):
                method = getattr(entitlements_backend, method_name)
                if callable(method):
                    entitlements[method_name] = method(request.user)
        entitlements["context"] = entitlements_backend.get_context(request.user)
        return drf.response.Response(entitlements)
