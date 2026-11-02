"""Replay committed events before waiting, preserving cursor and authority lifetime."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Protocol

from node_protocol.journal import JournalEvent


class EventHistory(Protocol):
    async def events_after(self, cursor: int) -> tuple[JournalEvent, ...]: ...


class ObserveNodeEvents:
    def __init__(self, history: EventHistory, changed: asyncio.Event) -> None:
        self._history, self._changed = history, changed

    async def read(self, cursor: int, expires_at: int) -> AsyncIterator[JournalEvent]:
        while expires_at > time.time():
            self._changed.clear()
            rows = await self._history.events_after(cursor)
            if not rows:
                try:
                    await asyncio.wait_for(
                        self._changed.wait(), timeout=max(0, expires_at - time.time())
                    )
                except TimeoutError:
                    return
            for row in rows:
                if expires_at <= int(time.time()):
                    return
                yield row
                cursor = row.cursor
