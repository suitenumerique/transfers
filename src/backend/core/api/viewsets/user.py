"""API ViewSet for User model."""

import rest_framework as drf
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets

from core import models

from .. import permissions, serializers


class UserViewSet(viewsets.GenericViewSet):
    """ViewSet for User model. Allows retrieving authenticated user information."""

    serializer_class = serializers.UserWithoutAbilitiesSerializer
    pagination_class = None
    queryset = models.User.objects.none()

    def get_serializer_class(self):
        if self.action == "get_me":
            return serializers.UserWithAbilitiesSerializer
        return super().get_serializer_class()

    def get_permissions(self):
        if self.action == "get_me":
            permission_classes = [permissions.IsAuthenticated & permissions.IsSelf]
        else:
            return super().get_permissions()
        return [permission() for permission in permission_classes]

    @extend_schema(
        tags=["users"],
        responses={
            200: serializers.UserWithAbilitiesSerializer,
            401: OpenApiResponse(
                description="Authentication credentials were not provided or are invalid.",
            ),
        },
    )
    @drf.decorators.action(
        detail=False,
        methods=["get"],
        url_name="me",
        url_path="me",
    )
    def get_me(self, request):
        """Return information on currently logged user."""
        context = {"request": request}
        serializer = self.get_serializer(request.user, context=context)
        return drf.response.Response(serializer.data)
