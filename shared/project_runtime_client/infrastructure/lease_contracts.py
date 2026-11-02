"""Field-exact runtime lease receipt schemas shared by verifier and caller."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RuntimeLeaseReceipt(BaseModel):
    """FIELD-EXACT accepted A9 Backend `_runtime_lease_attestation` DTO."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    runtime_session_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    actor_user_id: UUID
    owner_service_id: UUID
    owner_instance_uuid: UUID
    lease_nonce: UUID
    kind: Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
    state: Literal["active", "lost", "expired", "revoked", "closed"]
    revision: int = Field(ge=1)
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime
    cleanup_state: Literal["not_needed", "pending", "confirmed", "unknown"]


class SignedRuntimeLeaseReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    lease: RuntimeLeaseReceipt
    attestation_jws: str = Field(min_length=100, max_length=8192)
    attestation_expires_at: datetime
