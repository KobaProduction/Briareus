"""Read committed owner journals with bounded fair progress and durable cursors."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from control_panel_api.domain.owner_events import (
    EventAuthority,
    EventContractGap,
    EventFeed,
    EventSource,
    EventWindow,
    OwnerCursor,
    OwnerEvent,
)
from control_panel_api.domain.realtime_events import EventScope, RealtimeEvent
from control_panel_api.domain.realtime_payloads import SourceNoticeData

from .realtime_journal import resync_event as resync_notice

type RelayNotice = RealtimeEvent


@dataclass(frozen=True, slots=True)
class OwnerEventFailure:
    message: str


@dataclass(frozen=True, slots=True)
class OwnerCursorFailure:
    message: str


@dataclass(frozen=True, slots=True)
class OwnerEventPage:
    """Decoded page retaining the original per-item and final-cursor failure order."""

    items: tuple[OwnerEvent | EventContractGap | OwnerEventFailure, ...]
    truncated: bool
    continuation: OwnerCursor | OwnerCursorFailure | None

    def cursor(self) -> OwnerCursor | None:
        if isinstance(self.continuation, OwnerCursorFailure):
            raise ValueError(self.continuation.message)
        return self.continuation


class OwnerJournalPort(Protocol):
    async def read(self, feed: EventFeed, window: EventWindow) -> OwnerEventPage: ...


class OwnerEventSink(Protocol):
    async def publish(
        self,
        event: OwnerEvent,
        feed: EventFeed,
        authority: EventAuthority,
    ) -> None: ...


def source_notice(feed: EventFeed, kind: str) -> RealtimeEvent:
    return RealtimeEvent(
        "system.notifications",
        kind,
        datetime.now(UTC),
        SourceNoticeData(feed.source, feed.project),
        EventScope("broadcast"),
    )


@dataclass(slots=True)
class OwnerEventRelay:
    """State belongs to one browser connection; private adapters bind each fresh proof."""

    windows: dict[tuple[EventSource, str], EventWindow] = field(default_factory=dict)
    health: dict[tuple[EventSource, str], bool] = field(default_factory=dict)
    offset: int = 0

    def feeds(
        self, authority: EventAuthority, available: frozenset[EventSource]
    ) -> tuple[EventFeed, ...]:
        result: list[EventFeed] = []
        if "platform" in available:
            result.append(EventFeed("platform"))
        projects = [
            item for item in authority.projects if item.use_resources or item.approve_sessions
        ]
        selected = (projects + projects)[self.offset : self.offset + min(4, len(projects))]
        self.offset = (self.offset + 4) % max(1, len(projects))
        for project in selected:
            if "access" in available:
                result.append(EventFeed("access", project.project_uuid))
            if "resources" in available and authority.operator and project.use_resources:
                result.append(EventFeed("resources", project.project_uuid))
        return tuple(result)

    def window(self, feed: EventFeed) -> EventWindow:
        existing = self.windows.get(feed.key)
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        return EventWindow(now - timedelta(hours=23), now)

    def advance(
        self, feed: EventFeed, window: EventWindow, continuation: OwnerCursor | None
    ) -> None:
        if continuation is not None:
            self.windows[feed.key] = EventWindow(window.since, window.until, continuation)
        else:
            self.windows[feed.key] = EventWindow(
                window.until - timedelta(minutes=5), datetime.now(UTC)
            )

    async def process_page(
        self,
        page: OwnerEventPage,
        *,
        feed: EventFeed,
        authority: EventAuthority,
        sink: OwnerEventSink,
    ) -> AsyncIterator[RelayNotice]:
        if page.truncated:
            yield resync_notice(feed.source + ".retention")
        for item in page.items:
            if isinstance(item, OwnerEventFailure):
                raise ValueError(item.message)
            if isinstance(item, EventContractGap):
                yield resync_notice(feed.source + ".event_contract")
            else:
                await sink.publish(item, feed, authority)

    async def read(
        self,
        authority: EventAuthority,
        *,
        available: frozenset[EventSource],
        journal: OwnerJournalPort,
        sink: OwnerEventSink,
    ) -> AsyncIterator[RelayNotice]:
        for feed in self.feeds(authority, available):
            if authority.expires_at <= datetime.now(UTC):
                return
            window = self.window(feed)
            try:
                page = await journal.read(feed, window)
                async for notice in self.process_page(
                    page,
                    feed=feed,
                    authority=authority,
                    sink=sink,
                ):
                    yield notice
                self.advance(feed, window, page.cursor())
                if self.health.get(feed.key) is not True:
                    kind = (
                        "source.recovered"
                        if self.health.get(feed.key) is False
                        else "source.connected"
                    )
                    yield source_notice(feed, kind)
                self.health[feed.key] = True
            except Exception:
                if self.health.get(feed.key) is not False:
                    yield source_notice(feed, "source.unavailable")
                self.health[feed.key] = False
