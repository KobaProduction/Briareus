"""Read committed owner events without advancing a consumer acknowledgement."""

from datetime import UTC, datetime
from typing import Protocol

from authorization.domain.owner_events import (
    EventCursor,
    EventReadActor,
    EventWindow,
    OwnerEvent,
    OwnerEventPage,
)
from service_runtime._repository_binding import _RepositoryBinding


class OwnerEventRepositoryPort(Protocol):
    async def read(self, actor: EventReadActor, window: EventWindow) -> tuple[OwnerEvent, ...]: ...


class ReadOwnerEvents(_RepositoryBinding[OwnerEventRepositoryPort]):
    async def execute(self, actor: EventReadActor, requested: EventWindow) -> OwnerEventPage:
        window = requested.bounded(datetime.now(UTC))
        rows = await self.repository.read(actor, window)
        actor.require_current(datetime.now(UTC))
        last = rows[127] if len(rows) > 128 else None
        cursor = EventCursor(last.occurred_at, last.event_uuid) if last is not None else None
        return OwnerEventPage(rows[:128], window.truncated, cursor)
