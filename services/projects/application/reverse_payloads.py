"""Exact signed Reverse parameters and verified observation subsets; no coercion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ReserveNativeImportPayload:
    native_project_id: str
    file_object_id: str
    service_id: str
    instance_uuid: str
    auto_analyze: bool
    ttl_seconds: int
    file_version: int
    content_sha256: str
    size_bytes: int
    source_revision: str


@dataclass(frozen=True, slots=True)
class DispatchNativeImportPayload:
    import_uuid: str
    original_operation_uuid: str
    expected_import_version: int
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class NativeImportObservationPayload:
    native_project_id: str
    file_object_id: str
    outcome: Literal["succeeded", "confirmed_absent", "unknown"]
    native_artifact_id: str | None
    result_sha256: str | None
    observed_at: str
    native_scope_digest: str


@dataclass(frozen=True, slots=True)
class ReconcileNativeImportPayload:
    import_uuid: str
    original_operation_uuid: str
    expected_import_version: int
    service_id: str
    instance_uuid: str
    native_observation: NativeImportObservationPayload


@dataclass(frozen=True, slots=True)
class NativeImportRevisionPayload:
    import_uuid: str
    original_operation_uuid: str
    expected_version: int
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class InspectNativeImportPayload:
    import_uuid: str
    original_operation_uuid: str
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class InspectOriginalNativeImportPayload:
    original_operation_uuid: str
    service_id: str
    instance_uuid: str
