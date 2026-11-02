"""Bounded, overlapping read windows for committed owner signal projections.

Contains no database/credential access. Owners supply their own authorised
query; audit details, command bodies and encrypted outcomes are never projected.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .event_projection import EventItem, EventPage, EventRow


@dataclass(frozen=True)
class EventWindow:
    since: datetime
    until: datetime
    after: tuple[datetime, UUID] | None
    truncated: bool

    @classmethod
    def from_values(
        cls,
        since: datetime,
        until: datetime,
        after: tuple[datetime, UUID] | None,
        *,
        now: datetime | None = None,
    ) -> EventWindow:
        current = now if now is not None else datetime.now(UTC)
        if any(value.tzinfo is None for value in (current, since, until)):
            raise ValueError("Event timestamps must include a timezone")
        if since > until or until > current + timedelta(seconds=5):
            raise ValueError("Invalid event window")
        if after is not None and (after[0].tzinfo is None or not since <= after[0] <= until):
            raise ValueError("Invalid event cursor")
        floor = current - timedelta(hours=24)
        return cls(max(since, floor), until, after, since < floor)

    def result(self, rows: Sequence[EventRow]) -> EventPage:
        last = rows[127] if len(rows) > 128 else None
        cursor = (last.created_at.isoformat(), str(last.id)) if last else None
        items = tuple(EventItem.from_row(row) for row in rows[:128])
        return EventPage(self.truncated, cursor, items)
