"""Runtime stored vocabularies, owner lease claims and native observation facts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Kind = Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
RuntimeSessionState = Literal["active", "lost", "expired", "revoked", "closed"]
RuntimeCleanupState = Literal["not_needed", "pending", "confirmed", "unknown"]
RuntimeJobState = Literal["queued", "running", "succeeded", "failed", "unknown", "cancelled"]
JobOutcome = Literal["succeeded", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class RuntimeLease:
    runtime_session_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    actor_user_id: UUID
    kind: str
    owner_service_id: UUID
    owner_instance: UUID
    lease_nonce: UUID
    status: str
    version: int
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime
    cleanup_state: str


@dataclass(frozen=True, slots=True)
class RuntimeJob:
    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: UUID
    status: str
    version: int
    hard_expires_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeCleanupEvidence:
    runtime_session_uuid: UUID
    project_id: UUID
    owner_service_id: UUID
    previous_instance_uuid: UUID
    lease_nonce: UUID
    observed_stopped_at: datetime


@dataclass(frozen=True, slots=True)
class OwnerRuntimeLeaseClaim:
    runtime_session_uuid: UUID
    owner_service_id: UUID
    owner_instance: UUID
    project_id: UUID
    caller_user_id: UUID
    agent_session_uuid: UUID
    lease_nonce: UUID
    kind: Kind
    version: int
    lease_expires_at: datetime
    hard_expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeStopped:
    runtime_session_uuid: UUID
    project_id: UUID
    previous_owner_service_id: UUID
    previous_instance_uuid: UUID
    lease_nonce: UUID
    observed_stopped_at: datetime
    native_scope_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeJobObservation:
    job_uuid: UUID
    runtime_session_uuid: UUID
    project_id: UUID
    owner_service_id: UUID
    owner_instance: UUID
    lease_nonce: UUID
    outcome: JobOutcome
    result_sha256: str | None
    native_scope_digest: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeJobInspection:
    job_uuid: UUID
    runtime_session_uuid: UUID
    original_queue_operation: str
    original_lease_nonce: UUID
    status: str
    version: int
    hard_expires_at: datetime
    result_digest: str | None
    # A database row is a reported state; it does not attest OS liveness.
    native_process_verified: bool = False
    reconciliation_required: bool = True


def checked_job_outcome(value: str) -> JobOutcome:
    if value == "succeeded":
        return "succeeded"
    if value == "failed":
        return "failed"
    if value == "unknown":
        return "unknown"
    raise ValueError("unsupported runtime job outcome")


def is_runtime_cleanup_evidence(value: RuntimeCleanupEvidence) -> bool:
    return isinstance(value, RuntimeCleanupEvidence)
