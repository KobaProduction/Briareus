"""Existing human Access command shapes, independent of owner policy and storage."""

from collections.abc import Callable
from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_serializer, field_validator

from service_runtime._field_serialization import iso_timestamp

HandName = Literal["files", "terminal", "web", "svc", "reverse", "infrastructure", "serena"]


class AccessWire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceScopeWire(AccessWire):
    kind: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=512)


class EffectScopeWire(AccessWire):
    hand: HandName
    tool: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    resource: ResourceScopeWire


class RuntimeHumanIdentity(AccessWire):
    """Unverified transport fields; the owner must resolve the current actor."""

    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID
    project_uuid: UUID
    identity_expires_at: datetime

    existing_timestamp: ClassVar[Callable[[datetime], str]] = field_serializer(
        "identity_expires_at"
    )(staticmethod(iso_timestamp))


class AccessOperation(AccessWire):
    operation_uuid: UUID

    @field_validator("operation_uuid")
    @classmethod
    def operation_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("trusted operation requires UUIDv4")
        return value


class OpenSessionInput(AccessOperation):
    elevation_policy: Literal["fixed", "requestable"] = "requestable"
    label: str | None = Field(default=None, max_length=128)


class RequestElevationInput(AccessOperation):
    agent_session_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    resources: tuple[EffectScopeWire, ...] = Field(default=(), max_length=32)
    seconds: int = Field(strict=True, ge=1, le=300)


class ResolveElevationInput(AccessOperation):
    approval_uuid: UUID
    expected_approval_version: int = Field(strict=True, ge=1, le=2**63 - 1)
    approve: bool = Field(strict=True)
    allowed_operations: tuple[str, ...] | None = Field(default=None, max_length=32)


class RevokeSessionInput(AccessOperation):
    agent_session_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)


type AccessWriteInput = (
    OpenSessionInput | RequestElevationInput | ResolveElevationInput | RevokeSessionInput
)


class AccessListInput(AccessWire):
    limit: int = Field(strict=True, ge=1, le=50)


class SessionGetInput(AccessListInput):
    limit: int = Field(default=1, strict=True, ge=1, le=1)
    session_uuid: UUID


class RuntimeResourceInput(AccessWire):
    # The existing catalogue contract ignores unrelated command keys.
    model_config = ConfigDict(extra="ignore", frozen=True)
    hand: StrictStr = "terminal"
