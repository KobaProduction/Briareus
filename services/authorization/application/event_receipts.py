"""Named event-feed wire receipts consumed by HTTP and runtime adapters."""

from collections.abc import Callable
from functools import partial
from operator import is_
from uuid import UUID

from pydantic import BaseModel, Field


class EventCallResponse(BaseModel):
    hand: str
    tool: str
    status: str
    session_uuid: UUID | None
    node_uuid: UUID
    placement_uuid: UUID
    duration_ms: int
    transport: str


no_call: Callable[[EventCallResponse | None], bool] = partial(is_, None)


class OwnerEventResponse(BaseModel):
    event_id: str
    type: str
    occurredAt: str
    actor_id: str
    project_id: str
    operation_id: str
    entity_id: str
    call: EventCallResponse | None = Field(default=None, exclude_if=no_call)


class EventPageResponse(BaseModel):
    items: tuple[OwnerEventResponse, ...]
    truncated: bool
    next: tuple[str, str] | None
