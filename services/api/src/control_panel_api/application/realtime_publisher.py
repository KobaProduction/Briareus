"""Publish typed facts with an explicit visibility binding."""

from datetime import datetime
from typing import Protocol

from control_panel_api.domain.event_scope import EventScope
from control_panel_api.domain.realtime_payloads import RealtimeData


class EventPublisher(Protocol):
    async def emit(
        self,
        topic: str,
        event_type: str,
        data: RealtimeData,
        *,
        visibility: EventScope,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None: ...
