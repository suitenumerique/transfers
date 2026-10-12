"""Utils for the core app."""

from configurations import values


class ThrottleRateValue(values.Value):
    """
    A custom value class that parses and validates throttle rate strings
    like "1000/day" at startup.

    Stores the parsed tuple (limit, period_name, period_seconds) or None.
    Same format as suitenumerique/messages.
    """

    PERIOD_SECONDS = {
        "minute": 60,
        "hour": 3600,
        "day": 86400,
    }

    def setup(self, name):
        # django-configurations only parses values read from the environment:
        # parse the default too, so the setting is always a tuple or None.
        value = super().setup(name)
        if isinstance(value, str):
            value = self.value = self.to_python(value)
        return value

    def to_python(self, value):
        if not value:
            return None

        try:
            limit_str, period = value.split("/")
            limit = int(limit_str)
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"Invalid throttle rate format '{value}': expected 'number/period' "
                f"(e.g. '1000/day')"
            ) from e

        period = period.lower()
        period_seconds = self.PERIOD_SECONDS.get(period)
        if period_seconds is None:
            raise ValueError(
                f"Invalid throttle period '{period}': must be one of "
                f"{', '.join(self.PERIOD_SECONDS)}"
            )

        return (limit, period, period_seconds)
