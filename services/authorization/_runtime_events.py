"""Composition boundary for the read-only committed Access event projection."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from authorization.application.event_receipts import EventPageResponse
from authorization.application.owner_events import ReadOwnerEvents
from authorization.domain.owner_events import (
    EventReadActor,
    EventReaderExpired,
    EventWindow,
    InvalidEventWindow,
)
from authorization.infrastructure.owner_events import SqlOwnerEventRepository
from authorization.presentation.owner_events import page_response
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, InvalidInput


class EventReaderActor(Protocol):
    @property
    def actor_uuid(self) -> UUID: ...
    @property
    def project_uuid(self) -> UUID: ...
    @property
    def permissions(self) -> tuple[str, ...]: ...
    @property
    def expires_at(self) -> datetime: ...


async def read_events(
    database: PlatformDatabase,
    actor: EventReaderActor,
    window: EventWindow,
) -> EventPageResponse:
    current = EventReadActor(
        actor.actor_uuid, actor.project_uuid, actor.permissions, actor.expires_at
    )
    try:
        result = await ReadOwnerEvents(SqlOwnerEventRepository(database)).execute(current, window)
    except InvalidEventWindow as exc:
        raise InvalidInput(str(exc)) from exc
    except EventReaderExpired as exc:
        raise AccessDenied(str(exc)) from exc
    return page_response(result)
