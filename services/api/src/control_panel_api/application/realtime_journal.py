"""Bounded replay/history, visibility and cursor progress through invisible rows."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from control_panel_api.domain.realtime_events import (
    EventHistory,
    EventScope,
    RealtimeEvent,
    cursor_number,
    event_visible,
)
from control_panel_api.domain.realtime_payloads import ResyncRequired


class JournalUnavailable(ValueError):
    """Journal storage could not provide a bounded read."""


class EventJournalPort(Protocol):
    async def earliest(self) -> str | None: ...
    async def latest(self) -> str | None: ...
    async def newer(self, cursor: str, count: int) -> tuple[RealtimeEvent, ...]: ...
    async def older(self, before: str | None, count: int) -> tuple[RealtimeEvent, ...]: ...


def resync_event(reason: str | None = None) -> RealtimeEvent:
    return RealtimeEvent(
        "system.notifications",
        "resync.required",
        datetime.now(UTC),
        ResyncRequired(reason),
        EventScope("broadcast"),
    )


@dataclass(slots=True)
class HistoryScan:
    cursor: str | None
    items: list[RealtimeEvent] = field(default_factory=list)
    scanned: int = 0

    def collect(
        self,
        rows: tuple[RealtimeEvent, ...],
        proof: ResolvedPlatformUser,
        topics: set[str],
        project: str | None,
        limit: int,
    ) -> None:
        for event in rows:
            if event.cursor is None:
                raise ValueError("Journal row has no replay cursor")
            self.scanned += 1
            self.cursor = event.cursor
            if (
                event.topic in topics
                and event_visible(event, proof)
                and (project is None or str(event.project_id) == project)
            ):
                self.items.append(event)
            if len(self.items) == limit:
                break


class RealtimeJournal:
    def __init__(self, store: EventJournalPort) -> None:
        self._store = store

    async def _replay_rows(
        self, cursor: str | None, notices: list[RealtimeEvent]
    ) -> tuple[RealtimeEvent, ...]:
        if cursor is None:
            return tuple(reversed(await self._store.older(None, 200)))
        earliest, latest = await self._store.earliest(), await self._store.latest()
        if (
            earliest is None
            or latest is None
            or cursor_number(cursor) < cursor_number(earliest)
            or cursor_number(cursor) > cursor_number(latest)
        ):
            notices.append(resync_event("journal.retention"))
        rows = await self._store.newer(cursor, 2001)
        if len(rows) > 2000:
            notices.append(resync_event("journal.backlog"))
            rows = rows[-2000:]
        return rows

    async def replay(
        self, *, proof: ResolvedPlatformUser, topics: set[str], cursor: str | None
    ) -> tuple[RealtimeEvent, ...]:
        try:
            events: list[RealtimeEvent] = []
            rows = await self._replay_rows(cursor, events)
            events.extend(
                event for event in rows if event.topic in topics and event_visible(event, proof)
            )
            return tuple(events)
        except (JournalUnavailable, ValueError, KeyError):
            return (resync_event("broker.unavailable"),)

    async def history(
        self,
        *,
        proof: ResolvedPlatformUser,
        topics: set[str],
        before: str | None,
        project: str | None,
        limit: int,
    ) -> EventHistory:
        if project is not None and project not in {
            str(item.project_uuid) for item in proof.projects
        }:
            raise ValueError("JOURNAL_PROJECT_DENIED")
        scan = HistoryScan(before)
        async with asyncio.timeout(5):
            while len(scan.items) < limit and scan.scanned < 2000:
                rows = await self._store.older(scan.cursor, min(200, 2000 - scan.scanned))
                if not rows:
                    break
                scan.collect(rows, proof, topics, project, limit)
            more = bool(scan.cursor and await self._store.older(scan.cursor, 1))
            first = await self._store.earliest()
        expired = bool(before and first and cursor_number(before) < cursor_number(first))
        return EventHistory(tuple(scan.items), scan.cursor if more else None, more, expired)
