"""Transferts core API."""

import logging

from django.core.exceptions import ValidationError

from rest_framework import exceptions as drf_exceptions
from rest_framework import views as drf_views

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    """Handle Django ValidationError as DRF ValidationError."""
    if isinstance(exc, ValidationError):
        detail = None
        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        elif hasattr(exc, "message"):
            detail = exc.message
        elif hasattr(exc, "messages"):
            detail = exc.messages

        exc = drf_exceptions.ValidationError(detail=detail)

    return drf_views.exception_handler(exc, context)
