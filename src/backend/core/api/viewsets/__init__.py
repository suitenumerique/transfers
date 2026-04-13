"""API viewsets."""

from rest_framework.pagination import PageNumberPagination


class SerializerPerActionMixin:
    """Mixin to define serializer classes per action."""

    def get_serializer_class(self):
        if serializer_class := getattr(self, f"{self.action}_serializer_class", None):
            return serializer_class
        return super().get_serializer_class()


class Pagination(PageNumberPagination):
    """Pagination to display no more than 100 objects per page."""

    ordering = "-created_at"
    max_page_size = 200
    page_size_query_param = "page_size"
