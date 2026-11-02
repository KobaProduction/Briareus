"""Preserve the deployed event page JSON names and opaque cursor pair."""

from authorization.application.event_receipts import (
    EventCallResponse,
    EventPageResponse,
    OwnerEventResponse,
)
from authorization.domain.owner_events import EventCall, OwnerEvent, OwnerEventPage


def call_response(call: EventCall) -> EventCallResponse:
    return EventCallResponse(
        hand=call.hand,
        tool=call.tool,
        status=call.status,
        session_uuid=call.session_uuid,
        node_uuid=call.node_uuid,
        placement_uuid=call.placement_uuid,
        duration_ms=call.duration_ms,
        transport=call.transport,
    )


def event_response(event: OwnerEvent) -> OwnerEventResponse:
    return OwnerEventResponse(
        event_id=str(event.event_uuid),
        type=event.event_type,
        occurredAt=event.occurred_at.isoformat(),
        actor_id=str(event.actor_uuid),
        project_id=str(event.project_uuid),
        operation_id=event.operation_uuid,
        entity_id=event.entity_uuid,
        call=call_response(event.call) if event.call is not None else None,
    )


def page_response(page: OwnerEventPage) -> EventPageResponse:
    cursor = page.next_cursor
    return EventPageResponse(
        items=tuple(event_response(event) for event in page.items),
        truncated=page.truncated,
        next=(cursor.occurred_at.isoformat(), str(cursor.event_uuid))
        if cursor is not None
        else None,
    )
