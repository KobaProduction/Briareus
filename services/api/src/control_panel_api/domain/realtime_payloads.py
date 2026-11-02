"""Concrete facts delivered by the Panel journal, independent of JSON and brokers."""

from dataclasses import dataclass
from typing import Literal, NamedTuple
from uuid import UUID

from .owner_events import EventFeed, EventSource, McpOwnerEvent, OwnerEvent, event_topic

type RuntimeStatus = Literal["started", "unknown", "denied", "failed", "completed"]


@dataclass(frozen=True, slots=True)
class ProcessMetrics:
    source: Literal["control-panel-api"]
    uptime_seconds: int
    cpu_user_seconds: float
    cpu_system_seconds: float
    peak_memory_kib: int


@dataclass(frozen=True, slots=True)
class PanelCall:
    actor_id: UUID
    project_id: UUID
    hand: str
    tool: str
    operation_id: UUID
    status: RuntimeStatus
    duration_ms: int | float
    transport: Literal["panel-owner-rpc"] = "panel-owner-rpc"


@dataclass(frozen=True, slots=True)
class BrowserOperation:
    project_id: UUID
    operation_id: UUID
    tool: str
    status: RuntimeStatus


@dataclass(frozen=True, slots=True)
class PlatformMutation:
    action: str
    operation_id: UUID
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class AccessMutation:
    project_id: UUID
    actor_id: UUID
    operation_id: UUID


@dataclass(frozen=True, slots=True)
class AccessNotification:
    project_id: UUID
    action: str


@dataclass(frozen=True, slots=True)
class ConnectionMutation:
    project_id: UUID
    connection_id: UUID | None
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class NodeMutation:
    node_id: UUID | None
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class OwnerChange:
    event: OwnerEvent
    source: EventSource


@dataclass(frozen=True, slots=True)
class ResyncRequired:
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SourceNoticeData:
    source: EventSource
    project_id: UUID | None


type RealtimeData = (
    ProcessMetrics
    | PanelCall
    | BrowserOperation
    | PlatformMutation
    | AccessMutation
    | AccessNotification
    | ConnectionMutation
    | NodeMutation
    | OwnerChange
    | ResyncRequired
    | SourceNoticeData
)


def event_project(data: RealtimeData) -> UUID | None:
    if isinstance(data, OwnerChange):
        return data.event.project_id
    if isinstance(
        data,
        (
            PanelCall,
            BrowserOperation,
            AccessMutation,
            AccessNotification,
            ConnectionMutation,
            SourceNoticeData,
        ),
    ):
        return data.project_id
    return None


class EventKind(NamedTuple):
    topic: str
    event_type: str


def _event_kind(data: RealtimeData, event_type: str) -> EventKind:
    if isinstance(data, OwnerChange):
        feed = EventFeed(data.source, data.event.project_id)
        if not feed.accepts(data.event.type):
            raise ValueError("Unsupported owner notification")
        kind = (
            data.event.type.removeprefix("mcp.")
            if isinstance(data.event, McpOwnerEvent)
            else data.event.type
        )
        return EventKind(event_topic(feed, data.event), kind)
    if isinstance(data, ProcessMetrics):
        return EventKind("system.metrics", "process.snapshot")
    if isinstance(data, PanelCall):
        return EventKind("mcp.calls", "call." + data.status)
    if isinstance(data, BrowserOperation):
        return EventKind("browser.runtime", "operation." + data.status)
    if isinstance(data, PlatformMutation):
        return EventKind("management.events", data.action)
    if isinstance(data, AccessNotification):
        return EventKind("system.notifications", data.action)
    if isinstance(data, ResyncRequired):
        return EventKind("system.notifications", "resync.required")
    if isinstance(data, SourceNoticeData):
        return EventKind("system.notifications", event_type)
    return EventKind("management.events", event_type)


def require_event_contract(topic: str, event_type: str, data: RealtimeData) -> None:
    expected = _event_kind(data, event_type)
    if (topic, event_type) != expected:
        raise ValueError("Realtime event type does not match its data")
    if isinstance(data, SourceNoticeData) and event_type not in {
        "source.connected",
        "source.recovered",
        "source.unavailable",
    }:
        raise ValueError("Invalid owner source notice")
    if isinstance(data, (AccessMutation, AccessNotification)) and event_type not in {
        "session.open",
        "session.revoke",
        "session.request_elevation",
        "session.resolve_elevation",
    }:
        raise ValueError("Invalid Access management notice")
    if isinstance(data, ConnectionMutation) and event_type not in {
        "connection.create",
        "connection.update",
        "connection.delete",
    }:
        raise ValueError("Invalid connection mutation notice")
    if isinstance(data, NodeMutation) and not event_type.startswith("node."):
        raise ValueError("Invalid node mutation notice")
