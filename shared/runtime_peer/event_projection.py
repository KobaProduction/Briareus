"""Public owner-event projections, independent of persistence and transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


class EventRow(Protocol):
    """Only committed public facts may cross the owner projection boundary."""

    @property
    def id(self) -> UUID: ...

    @property
    def created_at(self) -> datetime: ...

    @property
    def action(self) -> str: ...

    @property
    def actor_user_id(self) -> UUID | None: ...

    @property
    def project_id(self) -> UUID | None: ...

    @property
    def object_id(self) -> str: ...

    @property
    def operation_uuid(self) -> UUID: ...


@dataclass(frozen=True)
class EventItem:
    """Names preserve the deployed public JSON contract, including occurredAt."""

    event_id: str
    occurredAt: str
    type: str
    actor_id: str | None
    project_id: str | None
    entity_id: str
    operation_id: str

    @classmethod
    def from_row(cls, row: EventRow) -> EventItem:
        return cls(
            event_id=str(row.id),
            occurredAt=row.created_at.isoformat(),
            type=row.action.removeprefix("panel."),
            actor_id=str(row.actor_user_id) if row.actor_user_id else None,
            project_id=str(row.project_id) if row.project_id else None,
            entity_id=row.object_id,
            operation_id=str(row.operation_uuid),
        )


@dataclass(frozen=True)
class EventPage:
    truncated: bool
    next: tuple[str, str] | None
    items: tuple[EventItem, ...]
