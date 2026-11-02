"""Exact owner effect request and receipt schemas, independent of orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from project_runtime_client.domain.authorization import (
    ProjectAccessDenied,
    ProjectAction,
    ProjectOwnerFence,
    ProjectPermit,
)
from project_runtime_client.domain.effect_protocol import (
    _DB,
    _PHASES,
    EffectOwner,
    EffectPhase,
    EffectState,
)
from project_runtime_client.domain.identifiers import valid_uuid


class OwnerFenceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    identity_version: int = Field(ge=1)
    identity_revocation_epoch: int = Field(ge=0)
    identity_authority_epoch: UUID
    control_state_version: int = Field(ge=1)
    control_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    control_scope_epoch: int = Field(ge=0)
    control_authority_epoch: UUID
    access_session_version: int = Field(ge=1)
    access_revocation_epoch: int = Field(ge=0)
    access_authority_epoch: UUID

    @classmethod
    def from_permit(cls, permit: ProjectPermit) -> OwnerFenceDTO:
        fence = permit.owner_fence
        if not isinstance(fence, ProjectOwnerFence) or not fence.valid():
            raise ProjectAccessDenied("OWNER_EFFECT_THREE_REVOCATION_FENCES_REQUIRED")
        return cls(
            identity_version=fence.identity_version,
            identity_revocation_epoch=fence.identity_revocation_epoch,
            identity_authority_epoch=fence.identity_authority_epoch,
            control_state_version=fence.control_state_version,
            control_revision=fence.control_revision,
            control_scope_epoch=fence.control_scope_epoch,
            control_authority_epoch=fence.control_authority_epoch,
            access_session_version=fence.access_session_version,
            access_revocation_epoch=fence.access_revocation_epoch,
            access_authority_epoch=fence.access_authority_epoch,
        )


class OwnerEffectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    protocol: Literal["owner-effect-command-v1"] = "owner-effect-command-v1"
    owner: EffectOwner
    owner_database: Literal[
        "briareus_resources", "briareus_files", "briareus_runtime", "briareus_reverse"
    ]
    phase: EffectPhase
    action: ProjectAction
    operation_uuid: UUID
    idempotency_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    actor_id: UUID
    recipient_service_id: UUID
    recipient_instance_uuid: UUID
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_type: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,95}$")
    expected_version: int = Field(ge=0)
    fence: OwnerFenceDTO

    @model_validator(mode="after")
    def check_owner(self) -> OwnerEffectCommand:
        if (
            self.owner_database != _DB[self.owner]
            or self.phase not in _PHASES[self.owner]
            or not valid_uuid(self.operation_uuid, version=4)
            or self.operation_uuid != self.idempotency_uuid
            or not valid_uuid(self.agent_session_uuid, version=4)
            or not valid_uuid(self.project_id, version=4)
            or not valid_uuid(self.actor_id, version=4)
            or not valid_uuid(self.recipient_service_id, version=4)
            or not valid_uuid(self.recipient_instance_uuid, version=4)
        ):
            raise ValueError("owner effect command id/database invalid")
        return self


class OwnerEffectReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    protocol: Literal["owner-effect-receipt-v1"] = "owner-effect-receipt-v1"
    owner: EffectOwner
    owner_database: Literal[
        "briareus_resources", "briareus_files", "briareus_runtime", "briareus_reverse"
    ]
    recipient_service_id: UUID
    recipient_instance_uuid: UUID
    project_id: UUID
    actor_id: UUID
    agent_session_uuid: UUID
    operation_uuid: UUID
    idempotency_uuid: UUID
    action: ProjectAction
    phase: EffectPhase
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_revision: int = Field(ge=1)
    state: EffectState
    fence: OwnerFenceDTO
    expires_at: datetime
    acknowledged_at: datetime

    @model_validator(mode="after")
    def check_owner(self) -> OwnerEffectReceipt:
        if (
            self.owner_database != _DB[self.owner]
            or self.phase not in _PHASES[self.owner]
            or not valid_uuid(self.operation_uuid, version=4)
            or self.idempotency_uuid != self.operation_uuid
            or not valid_uuid(self.agent_session_uuid, version=4)
            or not valid_uuid(self.project_id, version=4)
            or not valid_uuid(self.actor_id, version=4)
            or not valid_uuid(self.recipient_service_id, version=4)
            or not valid_uuid(self.recipient_instance_uuid, version=4)
            or self.expires_at.tzinfo is None
            or self.acknowledged_at.tzinfo is None
            or self.acknowledged_at > datetime.now(UTC)
        ):
            raise ValueError("owner effect reply invalid")
        return self


class SignedOwnerEffectReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    receipt: OwnerEffectReceipt
    attestation_jws: str = Field(min_length=100, max_length=8192)
