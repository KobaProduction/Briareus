"""Committed owner-event facts and scope rules, independent of their transport."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from .event_scope import EventScope

type EventSource = Literal["access", "platform", "resources"]
type McpHand = Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]
type GatewayCallStatus = Literal["completed", "failed", "unknown"]

MCP_TOOL_PATTERN = r"[A-Za-z][A-Za-z0-9_.-]{0,127}"
MAX_MCP_CALL_DURATION_MS = 86_400_000

ACCESS_EVENTS = frozenset(
    {
        "session.opened",
        "session.revoked",
        "session.revoked_by_parent",
        "session.elevation_requested",
        "session.elevation_resolved",
        "mcp.call.completed",
        "mcp.call.failed",
        "mcp.call.unknown",
    }
)
PLATFORM_EVENTS = frozenset(
    {
        "team.create",
        "team.rename",
        "team.member.add",
        "team.member.remove",
        "project.create",
        "project.rename",
        "user.link",
        "inviter.set",
        "invitation.issue",
    }
)
CONNECTION_EVENTS = frozenset(
    {
        "connection.create",
        "connection.update",
        "connection.delete",
        "node.register",
        "node.rename",
        "node.disable",
        "node.pair",
        "node.enable",
        "node.budget",
        "node.module.publish",
        "node.runtime_policy",
        "node.workspace.ensure",
        *(
            "node.module." + phase
            for phase in (
                "queued",
                "pulling",
                "stopping",
                "creating",
                "checking",
                "rolling_back",
                "succeeded",
                "failed",
                "unknown",
            )
        ),
    }
)


@dataclass(frozen=True, slots=True)
class EventProject:
    project_uuid: UUID
    use_resources: bool
    approve_sessions: bool


@dataclass(frozen=True, slots=True)
class EventAuthority:
    actor: UUID
    operator: bool
    expires_at: datetime
    projects: tuple[EventProject, ...]


@dataclass(frozen=True, slots=True)
class EventFeed:
    source: EventSource
    project: UUID | None = None

    @property
    def key(self) -> tuple[EventSource, str]:
        return self.source, str(self.project)

    def accepts(self, event_type: str) -> bool:
        if self.source == "access":
            return event_type in ACCESS_EVENTS
        if self.source == "platform":
            return event_type in PLATFORM_EVENTS
        return event_type in CONNECTION_EVENTS


@dataclass(frozen=True, slots=True)
class OwnerCursor:
    occurred_at: str
    event_id: UUID


@dataclass(frozen=True, slots=True)
class EventWindow:
    since: datetime
    until: datetime
    after: OwnerCursor | None = None


@dataclass(frozen=True, slots=True)
class OwnerEvent:
    # Field names deliberately match the deployed public event contract.
    event_id: UUID
    type: str
    occurredAt: str
    actor_id: UUID | None
    project_id: UUID | None
    operation_id: UUID | None
    entity_id: UUID | RuntimePolicyTarget | None

    def __post_init__(self) -> None:
        if datetime.fromisoformat(self.occurredAt).tzinfo is None:
            raise ValueError("Invalid owner event time")
        if (self.type == "node.runtime_policy") != isinstance(self.entity_id, RuntimePolicyTarget):
            raise ValueError("Invalid runtime policy selector")


@dataclass(frozen=True, slots=True)
class RuntimePolicyTarget:
    node_uuid: UUID | None = None

    @property
    def selector(self) -> str:
        return "server" if self.node_uuid is None else "node:" + str(self.node_uuid)


@dataclass(frozen=True, slots=True)
class McpCall:
    hand: McpHand
    tool: str
    status: GatewayCallStatus
    session_uuid: UUID | None
    node_uuid: UUID
    placement_uuid: UUID
    duration_ms: int
    transport: Literal["gateway-mcp"] = "gateway-mcp"

    def __post_init__(self) -> None:
        if re.fullmatch(MCP_TOOL_PATTERN, self.tool) is None:
            raise ValueError("Invalid call tool")
        if (
            type(self.duration_ms) is not int
            or not 0 <= self.duration_ms <= MAX_MCP_CALL_DURATION_MS
        ):
            raise ValueError("Invalid call duration")
        if self.status not in {"completed", "failed", "unknown"} or self.transport != "gateway-mcp":
            raise ValueError("Invalid call status or transport")


@dataclass(frozen=True, slots=True)
class McpOwnerEvent(OwnerEvent):
    call: McpCall

    def __post_init__(self) -> None:
        OwnerEvent.__post_init__(self)
        if self.call.status != self.type.removeprefix("mcp.call."):
            raise ValueError("Invalid call status or transport")


@dataclass(frozen=True, slots=True)
class EventContractGap:
    """An unknown event is a resync hint, never interpreted as an old contract."""

    source: EventSource


def visibility_for(feed: EventFeed, event: OwnerEvent, authority: EventAuthority) -> EventScope:
    if feed.source == "access":
        return EventScope("access", project=feed.project, actor=event.actor_id)
    if feed.source == "resources":
        return EventScope("project_operator", id=feed.project)
    if authority.operator:
        return EventScope("operator")
    return EventScope("actor", id=authority.actor)


def published_event_id(feed: EventFeed, event: OwnerEvent, authority: EventAuthority) -> str:
    identifier = feed.source + ":" + str(event.event_id)
    if feed.source == "platform" and not authority.operator:
        return identifier + ":" + str(authority.actor)
    return identifier


def event_topic(feed: EventFeed, event: OwnerEvent) -> str:
    if isinstance(event, McpOwnerEvent):
        return "mcp.calls"
    return "access.sessions" if feed.source == "access" else "management.events"
