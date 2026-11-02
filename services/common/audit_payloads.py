from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from service_runtime.audit_rendering import (
    _SENSITIVE_KEYS as _SENSITIVE_KEYS,
)
from service_runtime.audit_rendering import (
    _SENSITIVE_SUFFIXES as _SENSITIVE_SUFFIXES,
)
from service_runtime.audit_rendering import (
    _TEXT_SECRET_PATTERNS as _TEXT_SECRET_PATTERNS,
)
from service_runtime.audit_rendering import (
    MAX_PAYLOAD_CHARS as MAX_PAYLOAD_CHARS,
)
from service_runtime.audit_rendering import (
    REDACTED as REDACTED,
)
from service_runtime.audit_rendering import (
    _dataclass_value as _dataclass_value,
)
from service_runtime.audit_rendering import (
    _key_is_sensitive as _key_is_sensitive,
)
from service_runtime.audit_rendering import (
    _structured as _structured,
)
from service_runtime.audit_rendering import (
    redact_json as redact_json,
)
from service_runtime.audit_rendering import (
    redact_text as redact_text,
)
from service_runtime.audit_rendering import (
    render_error as render_error,
)
from service_runtime.audit_rendering import (
    render_payload as render_payload,
)


class FileQuotaConfiguredAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    quota_version: StrictInt
    byte_limit: StrictInt


class FileQuotaRevisionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    quota_revision: StrictInt


class FileQuotaReservationAudit(FileQuotaRevisionAudit):
    reservation_revision: StrictInt


class FileQuotaReservedAudit(FileQuotaReservationAudit):
    reserved_delta: StrictInt


class FileQuotaCommittedAudit(FileQuotaReservationAudit):
    file_version: StrictInt
    over_limit: StrictBool


class RuntimeSessionOpenedAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    service_id: StrictStr
    kind: StrictStr
    runtime_revision: StrictInt


class RuntimeRevisionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    runtime_revision: StrictInt


class RuntimeCleanupRequiredAudit(RuntimeRevisionAudit):
    cleanup_required: StrictBool


class RuntimeCleanupOwnerAudit(RuntimeCleanupRequiredAudit):
    owner_service_id: StrictStr


class RuntimeOwnerInstanceAudit(RuntimeRevisionAudit):
    owner_instance: UUID


class RuntimeSessionJobAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    runtime_session_uuid: StrictStr


class RuntimeJobRevisionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_version: StrictInt
    runtime_session_uuid: StrictStr


class RuntimeJobStatusAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_status: StrictStr
    job_version: StrictInt


class NativeProjectRegisteredAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    native_project_revision: StrictInt


class NativeImportReservedAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    native_project_id: UUID
    source_file_version: StrictInt


class NativeImportRevisionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    native_import_version: StrictInt


class NativeImportDispatchedAudit(NativeImportRevisionAudit):
    native_project_id: UUID


class NativeImportConfirmedAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    native_project_id: UUID
    native_import_version: StrictInt
    artifact_confirmed: StrictBool


class NativeImportReconciliationAudit(NativeImportRevisionAudit):
    reconciliation_required: StrictBool


class NativeSourceCleanupAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_file_object_id: UUID
    source_file_version: StrictInt
    native_artifact_preserved: StrictBool


class ResourceChangedAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    owner_scope: StrictStr
    owner_id: UUID
    resource_id: UUID
    resource_version: StrictInt
    owner_resource_revision: StrictInt
    invalidate_effective_project_cache: StrictBool
