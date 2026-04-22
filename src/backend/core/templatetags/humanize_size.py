"""Template filter that formats a byte count as a short human-readable
string (e.g. ``248 Mo``, ``6.8 Go``). French units to match the email mock.
"""

from django import template

register = template.Library()


@register.filter(name="humanize_size")
def humanize_size(value):
    try:
        b = float(value)
    except (TypeError, ValueError):
        return value
    if b < 1024:
        return f"{int(b)} o"
    if b < 1024 * 1024:
        return f"{b / 1024:.0f} Ko"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} Mo"
    return f"{b / (1024 * 1024 * 1024):.1f} Go"
