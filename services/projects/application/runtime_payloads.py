"""Exact signed Runtime parameters and verified observation subsets; no coercion."""

from __future__ import annotations

from dataclasses import dataclass

from projects.domain.runtime_ledger import JobOutcome, Kind


@dataclass(frozen=True, slots=True)
class OpenRuntimePayload:
    runtime_session_uuid: str
    service_id: str
    instance_uuid: str
    kind: Kind
    idle_ttl_seconds: int
    hard_ttl_seconds: int


@dataclass(frozen=True, slots=True)
class RenewRuntimePayload:
    runtime_session_uuid: str
    expected_version: int
    expected_lease_nonce: str
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class RevokeRuntimePayload:
    runtime_session_uuid: str
    expected_version: int
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class ConfirmRuntimeCleanupPayload:
    runtime_session_uuid: str
    previous_lease_nonce: str
    expected_version: int
    previous_service_id: str
    previous_instance_uuid: str
    supervisor_service_id: str
    supervisor_instance_uuid: str
    observed_stopped_at: str
    native_scope_digest: str


@dataclass(frozen=True, slots=True)
class QueueRuntimeJobPayload:
    runtime_session_uuid: str
    expected_lease_version: int
    expected_lease_nonce: str
    service_id: str
    instance_uuid: str
    payload_sha256: str
    hard_ttl_seconds: int


@dataclass(frozen=True, slots=True)
class DispatchRuntimeJobPayload:
    job_uuid: str
    runtime_session_uuid: str
    expected_lease_nonce: str
    expected_job_version: int
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class RuntimeJobRevisionPayload:
    job_uuid: str
    runtime_session_uuid: str
    original_lease_nonce: str
    expected_job_version: int
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class RuntimeJobObservationPayload:
    outcome: JobOutcome
    result_sha256: str | None
    native_scope_digest: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class ReconcileRuntimeJobPayload:
    job_uuid: str
    runtime_session_uuid: str
    original_lease_nonce: str
    expected_job_version: int
    service_id: str
    instance_uuid: str
    native_observation: RuntimeJobObservationPayload


@dataclass(frozen=True, slots=True)
class InspectRuntimeJobPayload:
    job_uuid: str
    runtime_session_uuid: str
    original_lease_nonce: str
    service_id: str
    instance_uuid: str
