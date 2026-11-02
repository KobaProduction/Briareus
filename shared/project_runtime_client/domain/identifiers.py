"""Identifier shape checks for untrusted runtime/provider boundaries."""

from uuid import UUID


def valid_uuid(value: object, *, version: int | None = None) -> bool:
    return isinstance(value, UUID) and (version is None or value.version == version)
