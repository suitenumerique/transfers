"""API viewsets."""

from rest_framework.pagination import PageNumberPagination


class Pagination(PageNumberPagination):
    """Pagination to display no more than 100 objects per page."""

    max_page_size = 200
    page_size_query_param = "page_size"
