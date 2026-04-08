"""Utility classes for the core application."""

import json

from configurations import values


class JSONValue(values.Value):
    """A Value subclass that parses a JSON string from environment variables."""

    def to_python(self, value):
        return json.loads(value)
