"""Concrete realtime boundary contracts, retaining the deployed JSON field layout."""

from collections.abc import Callable
from datetime import datetime
from functools import partial
from operator import is_
from typing import ClassVar, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer, model_validator

from control_panel_api.domain.event_scope import EventScope, ScopeKind
from control_panel_api.domain.owner_events import EventSource, McpOwnerEvent
from control_panel_api.domain.realtime_events import EventHistory, RealtimeEvent
from control_panel_api.domain.realtime_payloads import (
    AccessMutation,
    AccessNotification,
    BrowserOperation,
    ConnectionMutation,
    NodeMutation,
    OwnerChange,
    PanelCall,
    PlatformMutation,
    ProcessMetrics,
    RealtimeData,
    ResyncRequired,
    SourceNoticeData,
)
from service_runtime._field_serialization import iso_timestamp

from .owner_event_contracts import CanonicalUUID, McpCallWire, McpOwnerEventWire, OwnerEventWire

_absent: Callable[[object], bool] = partial(is_, None)


class EventScopeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: ScopeKind = ""
    id: CanonicalUUID | None = Field(default=None, exclude_if=_absent)
    project: CanonicalUUID | None = Field(default=None, exclude_if=_absent)
    actor: CanonicalUUID | None = Field(default=None, exclude_if=_absent)

    def domain(self) -> EventScope:
        return EventScope(self.kind, self.id, self.project, self.actor)


class OwnerPublication(OwnerEventWire):
    source: EventSource


class McpOwnerPublication(McpOwnerEventWire, McpCallWire):
    source: EventSource

    @model_validator(mode="after")
    def matching_projection(self) -> Self:
        if self.to_call() != self.call.to_call():
            raise ValueError("MCP notification projections disagree")
        return self


class ResyncPublication(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: str | None = Field(default=None, exclude_if=_absent)


type EventDataWire = (
    ProcessMetrics
    | PanelCall
    | BrowserOperation
    | PlatformMutation
    | AccessMutation
    | AccessNotification
    | ConnectionMutation
    | NodeMutation
    | OwnerPublication
    | McpOwnerPublication
    | ResyncPublication
    | SourceNoticeData
)


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topic: str
    type: str
    occurredAt: AwareDatetime
    data: EventDataWire
    scope: EventScopeEnvelope = Field(default_factory=EventScopeEnvelope)
    event_id: str | None = Field(default=None, exclude_if=_absent)
    version: int | None = Field(default=None, exclude_if=_absent)
    cursor: str | None = Field(default=None, exclude_if=_absent)

    iso_time: ClassVar[Callable[[datetime], str]] = field_serializer("occurredAt")(
        staticmethod(iso_timestamp)
    )

    def event(self) -> RealtimeEvent:
        if isinstance(self.data, (OwnerPublication, McpOwnerPublication)):
            data: RealtimeData = OwnerChange(self.data.domain(), self.data.source)
        elif isinstance(self.data, ResyncPublication):
            data = ResyncRequired(self.data.reason)
        else:
            data = self.data
        return RealtimeEvent(
            self.topic,
            self.type,
            self.occurredAt,
            data,
            self.scope.domain(),
            self.event_id,
            self.version,
            self.cursor,
        )

    @model_validator(mode="after")
    def matching_contract(self) -> Self:
        self.event()
        return self


class HistoryEnvelope(BaseModel):
    items: tuple[EventEnvelope, ...]
    next_cursor: str | None
    has_more: bool
    retention_gap: bool
    retention_limit: int


def _owner_publication(change: OwnerChange) -> OwnerPublication | McpOwnerPublication:
    event = change.event
    if isinstance(event, McpOwnerEvent):
        call = event.call
        return McpOwnerPublication(
            event_id=event.event_id,
            type=event.type,
            occurredAt=event.occurredAt,
            actor_id=event.actor_id,
            project_id=event.project_id,
            operation_id=event.operation_id,
            entity_id=event.entity_id,
            source=change.source,
            call=McpCallWire(
                hand=call.hand,
                tool=call.tool,
                status=call.status,
                session_uuid=call.session_uuid,
                node_uuid=call.node_uuid,
                placement_uuid=call.placement_uuid,
                duration_ms=call.duration_ms,
                transport=call.transport,
            ),
            hand=call.hand,
            tool=call.tool,
            status=call.status,
            session_uuid=call.session_uuid,
            node_uuid=call.node_uuid,
            placement_uuid=call.placement_uuid,
            duration_ms=call.duration_ms,
            transport=call.transport,
        )
    return OwnerPublication(
        event_id=event.event_id,
        type=event.type,
        occurredAt=event.occurredAt,
        actor_id=event.actor_id,
        project_id=event.project_id,
        operation_id=event.operation_id,
        entity_id=event.entity_id,
        source=change.source,
    )


def event_envelope(event: RealtimeEvent) -> EventEnvelope:
    if isinstance(event.data, OwnerChange):
        data: EventDataWire = _owner_publication(event.data)
    elif isinstance(event.data, ResyncRequired):
        data = ResyncPublication(reason=event.data.reason)
    else:
        data = event.data
    scope = event.scope
    return EventEnvelope(
        topic=event.topic,
        type=event.type,
        occurredAt=event.occurred_at,
        data=data,
        scope=EventScopeEnvelope(
            kind=scope.kind, id=scope.id, project=scope.project, actor=scope.actor
        ),
        event_id=event.event_id,
        version=event.version,
        cursor=event.cursor,
    )


def history_envelope(page: EventHistory) -> HistoryEnvelope:
    return HistoryEnvelope(
        items=tuple(event_envelope(item) for item in page.items),
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        retention_gap=page.retention_gap,
        retention_limit=page.retention_limit,
    )


def decode_event(raw: str) -> RealtimeEvent:
    return EventEnvelope.model_validate_json(raw).event()


def encode_event(event: RealtimeEvent) -> str:
    return event_envelope(event).model_dump_json()
