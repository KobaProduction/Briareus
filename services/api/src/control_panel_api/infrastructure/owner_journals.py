"""Existing private owner transports adapted to the typed journal relay ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from control_panel_api._platform_unix_peer import UnixPlatformPeer
from control_panel_api._runtime_access_client import RuntimeAccessClient
from control_panel_api.application.owner_event_relay import OwnerEventPage
from control_panel_api.application.realtime_publisher import EventPublisher
from control_panel_api.domain.owner_events import (
    EventAuthority,
    EventFeed,
    EventSource,
    EventWindow,
    McpOwnerEvent,
    OwnerEvent,
    event_topic,
    published_event_id,
    visibility_for,
)
from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from control_panel_api.domain.realtime_payloads import OwnerChange
from runtime_peer import PeerClient
from runtime_peer.event_window_wire import EventWindowRequest
from runtime_peer.platform_management_wire import ManagementEnvelope
from runtime_peer.response_decoding import successful_reply

from .owner_event_decoder import decode_page


class WireEventWindow(EventWindowRequest):
    @classmethod
    def from_window(cls, window: EventWindow) -> WireEventWindow:
        after = None
        if window.after is not None:
            after = window.after.occurred_at, str(window.after.event_id)
        return cls(since=window.since.isoformat(), until=window.until.isoformat(), after=after)


def platform_event_page(status: int, body: object) -> OwnerEventPage:
    if status != 200:
        raise ValueError("Platform event source unavailable")
    return decode_page(body, EventFeed("platform"))


@dataclass(frozen=True, slots=True)
class PrivateOwnerJournals:
    proof: ResolvedPlatformUser
    access: RuntimeAccessClient | None
    platform: UnixPlatformPeer | None
    resources: PeerClient | None

    @property
    def available(self) -> frozenset[EventSource]:
        sources: set[EventSource] = set()
        if self.access is not None:
            sources.add("access")
        if self.platform is not None:
            sources.add("platform")
        if self.resources is not None:
            sources.add("resources")
        return frozenset(sources)

    async def read(self, feed: EventFeed, window: EventWindow) -> OwnerEventPage:
        state = WireEventWindow.from_window(window)
        if feed.source == "access":
            return await self.access_page(feed, state)
        if feed.source == "platform":
            return await self.platform_page(state)
        return await self.resources_page(feed, state)

    async def access_page(self, feed: EventFeed, window: WireEventWindow) -> OwnerEventPage:
        if self.access is None or feed.project is None:
            raise ValueError("Access event source unavailable")
        return await self.access.for_actor(self.proof).events(
            actor=self.proof.user_uuid,
            project=feed.project,
            window=window,
        )

    async def platform_page(self, window: WireEventWindow) -> OwnerEventPage:
        if self.platform is None:
            raise ValueError("Platform event source unavailable")
        return await self.platform.management(
            ManagementEnvelope(
                issuer=self.proof.issuer,
                subject=self.proof.subject,
                operation_uuid=uuid4(),
                action="events.read",
                data=window,
            ),
            expires_at=self.proof.expires_at,
            decode=platform_event_page,
        )

    async def resources_page(self, feed: EventFeed, window: WireEventWindow) -> OwnerEventPage:
        if self.resources is None:
            raise ValueError("Resources event source unavailable")
        _owner_reply = await self.resources.call(
            "/internal/v1/resources/connections",
            {
                "issuer": self.proof.issuer,
                "subject": self.proof.subject,
                "actor_uuid": str(self.proof.user_uuid),
                "project_uuid": str(feed.project),
                "identity_expires_at": self.proof.expires_at.isoformat(),
                "action": "events.read",
                "event_window": window.model_dump(mode="json"),
            },
            decode=successful_reply(lambda value: decode_page(value, feed)),
        )
        status, reply = _owner_reply.status, _owner_reply.body
        if status != 200 or reply is None:
            raise ValueError("Resources event source unavailable")
        return reply


@dataclass(frozen=True, slots=True)
class PanelOwnerEventSink:
    publisher: EventPublisher

    async def publish(self, event: OwnerEvent, feed: EventFeed, authority: EventAuthority) -> None:
        visibility = visibility_for(feed, event, authority)
        data = OwnerChange(event, feed.source)
        event_type = (
            event.type.removeprefix("mcp.") if isinstance(event, McpOwnerEvent) else event.type
        )
        await self.publisher.emit(
            event_topic(feed, event),
            event_type,
            data,
            visibility=visibility,
            event_id=published_event_id(feed, event, authority),
            occurred_at=datetime.fromisoformat(event.occurredAt),
        )
