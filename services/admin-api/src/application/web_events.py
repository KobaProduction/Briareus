"""Typed event publication shared by the retained administration route families."""

from typing import Protocol

from application.realtime_details import RealtimeDetails


class AdminWebEvents(Protocol):
    async def publish(self, event_type: str, data: RealtimeDetails) -> None: ...
