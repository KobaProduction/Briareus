"""Existing UUIDv4 requirement with the caller's unchanged InvalidInput failure."""

from uuid import UUID

from common.platform_errors import InvalidInput


def require_uuid_v4(value: UUID, failure: str) -> None:
    if not isinstance(value, UUID):
        raise InvalidInput(failure)
    if value.version != 4:
        raise InvalidInput(failure)
