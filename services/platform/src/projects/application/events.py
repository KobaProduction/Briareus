"""Read a bounded public event projection under the supplied current authority."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from projects.domain.management import ManagementError
from runtime_peer.event_projection import EventPage
from runtime_peer.event_window import EventWindow


@dataclass(frozen=True, slots=True)
class PlatformEventQuery:
    window: EventWindow
    visible_entities: tuple[str, ...] | None


class PlatformEventReader(Protocol):
    async def read(self, query: PlatformEventQuery) -> EventPage: ...


class ReadPlatformEvents:
    def __init__(self, reader: PlatformEventReader, now: Callable[[], datetime]) -> None:
        self._reader = reader
        self._now = now

    async def execute(self, query: PlatformEventQuery, deadline: datetime) -> EventPage:
        result = await self._reader.read(query)
        if deadline <= self._now():
            raise ManagementError(403, "CURRENT_OPERATOR_REQUIRED")
        return result
