"""Bounded committed-event windows and cursor/authority invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


class InvalidEventWindow(Exception):
    """The requested event window or resume cursor is invalid."""


class EventReaderExpired(Exception):
    """Current owner event-read authority expired during the SQL query."""


@dataclass(frozen=True, slots=True)
class EventReadActor:
    actor_uuid: UUID
    project_uuid: UUID
    permissions: tuple[str, ...]
    expires_at: datetime

    @property
    def can_read_all(self) -> bool:
        return "approve_agent_session" in self.permissions

    def require_current(self, now: datetime) -> None:
        if self.expires_at <= now:
            raise EventReaderExpired("Event reader authority expired")


@dataclass(frozen=True, slots=True)
class EventCursor:
    occurred_at: datetime
    event_uuid: UUID


@dataclass(frozen=True, slots=True)
class EventWindow:
    since: datetime
    until: datetime
    after: EventCursor | None
    truncated: bool = False

    def bounded(self, now: datetime) -> EventWindow:
        if (
            self.since.tzinfo is None
            or self.until.tzinfo is None
            or self.since > self.until
            or self.until > now + timedelta(seconds=5)
        ):
            raise InvalidEventWindow("Invalid event window")
        floor = now - timedelta(hours=24)
        since = max(self.since, floor)
        if self.after is not None and (
            self.after.occurred_at.tzinfo is None
            or not since <= self.after.occurred_at <= self.until
        ):
            raise InvalidEventWindow("Invalid event cursor")
        return EventWindow(since, self.until, self.after, self.since < floor)


@dataclass(frozen=True, slots=True)
class EventCall:
    hand: str
    tool: str
    status: str
    session_uuid: UUID | None
    node_uuid: UUID
    placement_uuid: UUID
    duration_ms: int
    transport: str


@dataclass(frozen=True, slots=True)
class OwnerEvent:
    event_uuid: UUID
    event_type: str
    occurred_at: datetime
    actor_uuid: UUID
    project_uuid: UUID
    operation_uuid: str
    entity_uuid: str
    call: EventCall | None


@dataclass(frozen=True, slots=True)
class OwnerEventPage:
    items: tuple[OwnerEvent, ...]
    truncated: bool
    next_cursor: EventCursor | None
