"""Decode native identifier scalars without changing provider-owned formats."""

from uuid import UUID


def preserved_identifier(value: object) -> UUID | str:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError("Native UUID or opaque identifier required")
    try:
        identifier = UUID(value)
    except ValueError:
        return value
    # Keep noncanonical UUID-looking provider values byte-for-byte intact too.
    return identifier if str(identifier) == value else value
