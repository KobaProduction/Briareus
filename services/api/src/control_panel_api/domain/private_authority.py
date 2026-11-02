"""Private delegated authority is exact, bounded and timezone unambiguous."""

from datetime import datetime


def current_deadline(value: object, *, now: datetime, upper: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and now < value <= upper


def exact_text(value: object, expected: str) -> bool:
    return isinstance(value, str) and value == expected
