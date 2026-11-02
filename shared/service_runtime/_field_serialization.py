"""Existing scalar wire serialization without field or model definitions."""

from datetime import datetime
from uuid import UUID


def iso_timestamp(value: datetime) -> str:
    return value.isoformat()


def uuid_hex(value: UUID) -> str:
    return value.hex
