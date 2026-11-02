"""Scoped realtime facts and journal pagination independent of Valkey and WebSocket."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from .event_scope import EventScope as EventScope
from .platform_authority import ResolvedPlatformUser
from .realtime_payloads import RealtimeData, event_project, require_event_contract


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    topic: str
    type: str
    occurred_at: datetime
    data: RealtimeData
    scope: EventScope = field(default_factory=lambda: EventScope(""))
    event_id: str | None = None
    version: int | None = None
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("Realtime event requires a timezone-aware timestamp")
        require_event_contract(self.topic, self.type, self.data)

    @property
    def project_id(self) -> UUID | None:
        return event_project(self.data)


@dataclass(frozen=True, slots=True)
class EventHistory:
    items: tuple[RealtimeEvent, ...]
    next_cursor: str | None
    has_more: bool
    retention_gap: bool
    retention_limit: int = 20_000


def event_visible(event: RealtimeEvent, proof: ResolvedPlatformUser) -> bool:
    scope = event.scope
    if scope.kind == "broadcast":
        return True
    if scope.kind == "operator":
        return proof.role == "operator"
    if scope.kind == "actor":
        return scope.id == proof.user_uuid
    projects = {project.project_uuid for project in proof.projects}
    if scope.kind == "project_operator":
        return proof.role == "operator" and scope.id in projects
    if scope.kind == "project":
        return scope.id in projects
    if scope.kind == "access":
        return any(
            project.project_uuid == scope.project
            and (scope.actor == proof.user_uuid or "approve_agent_session" in project.permissions)
            for project in proof.projects
        )
    return False


def cursor_number(cursor: str) -> tuple[int, ...]:
    return tuple(map(int, cursor.split("-")))
