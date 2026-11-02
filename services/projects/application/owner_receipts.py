"""Named owner command receipts before durable ledger serialization."""

from __future__ import annotations

from pydantic import BaseModel


class CatalogMetadataRecord(BaseModel):
    resource_id: str
    kind: str
    owner_scope: str
    owner_id: str
    name_key: str
    version: int


class FilesIndexEntry(BaseModel):
    file_id: str
    path_digest: str
    version: int
    size_bytes: int
    content_sha256: str | None


class CatalogChangeIntegration(BaseModel):
    resource_id: str
    version: int
    owner_scope: str
    revoked: bool


class CatalogChangeVariable(BaseModel):
    resource_id: str
    version: int
    owner_scope: str
    revoked: bool
    is_secret: bool


class CatalogCreateIntegration(BaseModel):
    resource_id: str
    owner_scope: str
    alias_key: str
    version: int
    credential_configured: bool


class CatalogCreateVariable(BaseModel):
    resource_id: str
    owner_scope: str
    name_key: str
    version: int
    is_secret: bool


class CatalogListMetadataCommitted(BaseModel):
    status: str
    kind: str
    scope: str
    alias_key: str | None
    limit: int
    project_id: str
    records: list[CatalogMetadataRecord]
    count: int
    source_secret_included: bool


class CatalogReserveIntegration(BaseModel):
    lease_id: str
    owner_scope: str
    owner_id: str
    resource_version: int
    expires_at: str


class CatalogReserveVariable(BaseModel):
    lease_id: str
    owner_scope: str
    owner_id: str
    resource_version: int
    expires_at: str
    credential_configured: bool


class CatalogResolveMetadataCommitted(BaseModel):
    status: str
    resource_id: str
    owner_scope: str
    owner_id: str
    name_key: str
    kind: str
    version: int
    source_secret_included: bool


class CatalogRevokeUnusedLease(BaseModel):
    status: str
    lease_id: str
    resource_id: str
    secret_returned: bool


class ControlConfirmProjectDelete(BaseModel):
    project_id: str
    lifecycle_status: str
    version: int
    resource_revision: int
    native_artifacts_removed: bool
    physical_cleanup_verified: bool


class ControlCreateAgent(BaseModel):
    agent_id: str
    project_id: str
    resource_revision: int


class ControlMovePersonalToTeam(BaseModel):
    project_id: str
    owner_team_id: str
    version: int
    resource_revision: int


class ControlPrepareProjectDelete(BaseModel):
    project_id: str
    lifecycle_status: str
    fenced_control_revision: int
    resource_revision: int
    reconciliation_required: bool


class ControlWithdrawTeamProject(BaseModel):
    project_id: str
    owner_user_id: str
    version: int
    resource_revision: int


class FilesConfigureQuota(BaseModel):
    project_id: str
    quota_version: int
    byte_limit: int
    frozen: bool


class FilesListFileIndex(BaseModel):
    status: str
    project_id: str
    files: list[FilesIndexEntry]
    has_more: bool
    next_after_id: str | None
    native_directory_verified: bool


class FilesMarkDispatched(BaseModel):
    reservation_id: str
    operation_uuid: str
    reservation_version: int
    status: str


class FilesMarkUnknown(BaseModel):
    reservation_id: str
    original_operation_uuid: str
    status: str
    version: int
    reconciliation_required: bool
    quota_frozen: bool


class FilesMetadataAsCommittedRead(BaseModel):
    status: str
    project_id: str
    path_digest: str
    file_id: str | None
    file_version: int | None
    size_bytes: int | None
    content_sha256: str | None
    native_file_verified: bool


class FilesReconcileWrite(BaseModel):
    reservation_id: str
    reservation_version: int
    quota_version: int
    status: str
    reserved_bytes: int


class FilesReleaseUndispatched(BaseModel):
    reservation_id: str
    original_operation_uuid: str
    status: str
    version: int
    reserved_bytes: int
    native_effect_verified: bool


class FilesReserveWrite(BaseModel):
    reservation_id: str
    operation_uuid: str
    quota_version: int
    reserved_delta: int
    status: str
    expires_at: str


class ReverseCancelBeforeDispatch(BaseModel):
    import_uuid: str
    status: str
    original_operation_uuid: str
    version: int
    native_effect_verified: bool


class ReverseMarkDispatched(BaseModel):
    import_uuid: str
    status: str
    version: int
    operation_uuid: str


class ReverseMarkUnknown(BaseModel):
    import_uuid: str
    original_operation_uuid: str
    status: str
    version: int
    native_effect_verified: bool
    reconciliation_required: bool


class ReverseReconcileImport(BaseModel):
    import_uuid: str
    status: str
    version: int
    reconciliation_required: bool


class ReverseReserveImport(BaseModel):
    import_uuid: str
    operation_uuid: str
    native_project_id: str
    source_file_version: int
    status: str
    version: int


class RuntimeCancelUndispatchedJob(BaseModel):
    job_uuid: str
    status: str
    version: int
    native_process_verified: bool


class RuntimeConfirmCleanup(BaseModel):
    runtime_session_uuid: str
    cleanup_state: str
    status: str
    version: int
    confirmed_stopped_at: str


class RuntimeDispatchJob(BaseModel):
    job_uuid: str
    status: str
    job_version: int
    lease_nonce: str


class RuntimeMarkJobUnknown(BaseModel):
    job_uuid: str
    status: str
    version: int
    original_lease_nonce: str
    reconciliation_required: bool
    native_process_verified: bool


class RuntimeOpenRuntime(BaseModel):
    runtime_session_uuid: str
    lease_nonce: str
    lease_version: int
    lease_expires_at: str
    owner_jws: str


class RuntimeQueueJob(BaseModel):
    job_uuid: str
    runtime_session_uuid: str
    status: str
    job_version: int
    lease_nonce: str
    hard_expires_at: str


class RuntimeReconcileNativeJob(BaseModel):
    job_uuid: str
    status: str
    version: int
    result_digest: str | None
    reconciliation_required: bool
    native_process_verified: bool


class RuntimeRenewRuntime(BaseModel):
    runtime_session_uuid: str
    lease_nonce: str
    lease_version: int
    lease_expires_at: str
    owner_jws: str


class RuntimeRevokeRuntime(BaseModel):
    runtime_session_uuid: str
    lease_version: int
    status: str
    cleanup_state: str
