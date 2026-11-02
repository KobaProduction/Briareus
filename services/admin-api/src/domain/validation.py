"""Primitive value checks shared by framework-free Admin domain records."""

from datetime import datetime


def require_boolean(value: object, *, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")


def require_integer(
    value: object, *, name: str, minimum: int = 0, maximum: int | None = None
) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")


def require_text(value: object, *, name: str, minimum: int = 0, maximum: int | None = None) -> None:
    if not isinstance(value, str) or len(value) < minimum:
        raise ValueError(f"{name} must be a string of length at least {minimum}")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{name} must have at most {maximum} characters")


def require_datetime(value: object, *, name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
