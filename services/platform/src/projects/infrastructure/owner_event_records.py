"""Existing Platform outbox variants; notifications never confer authority."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, field_validator

from common.infrastructure.owner_event_records import OwnerMutationEvent, TeamChangedEvent
from runtime_peer.identifiers import preserved_identifier


class EntityChangedEvent(BaseModel):
    """An internal entity UUID or an opaque Rauthy-issued user reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID | Annotated[str, Field(min_length=1, max_length=256)]

    identifier = field_validator("id", mode="before")(staticmethod(preserved_identifier))


class OperatorWorkspaceCreated(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: UUID
    owner_user_id: UUID


class OperatorBootstrapped(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: UUID
    revision: StrictInt = Field(ge=1)


type PlatformEvent = (
    OwnerMutationEvent
    | TeamChangedEvent
    | EntityChangedEvent
    | OperatorWorkspaceCreated
    | OperatorBootstrapped
)

PLATFORM_EVENT = TypeAdapter[PlatformEvent](PlatformEvent)
