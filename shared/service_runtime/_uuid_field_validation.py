"""Existing exact UUID field validation values, without model or transport dependencies."""

from uuid import UUID


def _project_uuid_v4(value: UUID) -> UUID:
    if value.version != 4:
        raise ValueError("Project must be UUIDv4")
    return value


def _team_uuid_v4(value: UUID | None) -> UUID | None:
    if value is not None and value.version != 4:
        raise ValueError("Team scope identifier must be UUIDv4")
    return value


def _operation_uuid_v4(value: UUID) -> UUID:
    if value.version != 4:
        raise ValueError("Operation must be UUIDv4")
    return value
