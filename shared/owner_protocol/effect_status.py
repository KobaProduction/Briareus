"""Signed owner-status wire schemas; persistence and authority stay at the owner."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

type OwnerStatusState = Literal["UNKNOWN", "COMMITTED", "DENIED"]


class OwnerEffectStatusV2(BaseModel):
    """Strict signed UNKNOWN cannot be relabeled as COMMITTED by any caller."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    protocol: Literal["owner-effect-status-v2"] = "owner-effect-status-v2"
    owner: Literal["catalog", "files", "execution", "reverse"]
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
    phase: str = Field(min_length=1, max_length=48)
    action: str = Field(min_length=1, max_length=64)
    original_idempotency_key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_revision: int = Field(ge=1)
    state: OwnerStatusState
    result_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_at: datetime
    expires_at: datetime
    reconciliation_required: bool = True
    retry_with_new_key_allowed: Literal[False] = False


class SignedOwnerEffectStatusV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    status: OwnerEffectStatusV2
    attestation_jws: str = Field(min_length=100, max_length=8192)
