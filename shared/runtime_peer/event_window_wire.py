"""Concrete event-window wire values, separate from retention and cursor policy."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictStr

from runtime_peer.event_window import EventWindow


class EventWindowFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    since: StrictStr
    until: StrictStr
    after: tuple[StrictStr, StrictStr] | None = None


class EventWindowRequest(EventWindowFields):
    def window(self, *, now: datetime | None = None) -> EventWindow:
        cursor = (
            None
            if self.after is None
            else (datetime.fromisoformat(self.after[0]), UUID(self.after[1]))
        )
        return EventWindow.from_values(
            datetime.fromisoformat(self.since), datetime.fromisoformat(self.until), cursor, now=now
        )
