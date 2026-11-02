"""Strict owner command wire DTO and attested recipient value."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from service_runtime._uuid_field_validation import _team_uuid_v4

from .domain.authority import OwnerAuthorityUnavailable, OwnerName


def _idempotency_key(value: str) -> str:
    # Preserve accepted HTTP Idempotency-Key contract across owner DBs.
    if not value.isascii() or not value.isprintable():
        raise ValueError("Idempotency-Key must be printable ASCII")
    return value


class OwnerCommandDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_uuid: UUID
    caller_user_id: UUID
    project_id: UUID
    session_uuid: UUID
    target_owner: OwnerName
    operation: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_identity_revision: int = Field(ge=1)
    expected_control_revision: int = Field(ge=1)
    expected_control_resource_revision: int = Field(ge=0)
    expected_team_id: UUID | None = None
    expected_team_revision: int | None = Field(default=None, ge=1)
    expected_team_resource_revision: int | None = Field(default=None, ge=0)
    expected_access_revision: int = Field(ge=1)

    _team_uuid = field_validator("expected_team_id")(staticmethod(_team_uuid_v4))

    _original_key = field_validator("idempotency_key")(staticmethod(_idempotency_key))

    @field_validator("operation_uuid", "caller_user_id", "project_id", "session_uuid")
    @classmethod
    def _v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("operation and authority identifiers must be UUIDv4")
        return value


@dataclass(frozen=True, slots=True)
class VerifiedOwnerServicePeer:
    """Produced by trusted mTLS/Unix peer verifier, not by request headers."""

    service_id: UUID
    instance_uuid: UUID
    audience: str
    signing_key_id: UUID
    transport: Literal["mtls", "unix-peer"]
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            self.service_id.version != 4
            or self.instance_uuid.version != 4
            or self.signing_key_id.version != 4
            or not self.audience.startswith("briareus:")
            or self.expires_at.tzinfo is None
            or self.expires_at <= datetime.now(UTC)
            or self.transport not in {"mtls", "unix-peer"}
        ):
            raise OwnerAuthorityUnavailable("service peer identity was not attested")
