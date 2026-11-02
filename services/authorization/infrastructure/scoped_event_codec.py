"""Decode legacy event JSONB without exposing provider data or credentials."""

import re
from dataclasses import replace
from uuid import UUID

from authorization.domain.scoped_event_policy import (
    PublicScopePayload,
    ScopeProvenance,
)
from authorization.infrastructure.journal_records import (
    AccessOutboxEvent,
    ApprovalAudit,
    AuditDetails,
    ConsentAudit,
    LeaseRedemptionAudit,
    LegacySecurityEvent,
    ProjectPersonalTransferAudit,
    ProjectReassignmentAudit,
    ProjectTeamTransferAudit,
    TeamMemberAudit,
    TeamMemberOwnerAudit,
    TeamOwnerAudit,
)
from common.audit_payloads import (
    FileQuotaCommittedAudit,
    FileQuotaReservationAudit,
    FileQuotaRevisionAudit,
    NativeImportConfirmedAudit,
    NativeImportDispatchedAudit,
    NativeImportReconciliationAudit,
    NativeImportReservedAudit,
    NativeImportRevisionAudit,
    NativeSourceCleanupAudit,
    ResourceChangedAudit,
    RuntimeCleanupRequiredAudit,
    RuntimeJobRevisionAudit,
    RuntimeJobStatusAudit,
    RuntimeRevisionAudit,
    RuntimeSessionOpenedAudit,
)


def parse_scope_uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        identifier = UUID(value)
        return identifier if identifier.version == 4 else None
    except (ValueError, TypeError):
        return None


def _public_text(value: object) -> str | None:
    return (
        value if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", value) else None
    )


def _public_revision(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _public_flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _native_identifier(value: object) -> str | int | None:
    return _public_text(value) if isinstance(value, str) else _public_revision(value)


def decode_public_scope_payload(raw: object) -> PublicScopePayload:
    if not isinstance(raw, dict):
        return PublicScopePayload()
    return PublicScopePayload(
        owner_scope=_public_text(raw.get("owner_scope")),
        owner_id=parse_scope_uuid(raw.get("owner_id")),
        team_id=parse_scope_uuid(raw.get("team_id")),
        new_owner_id=parse_scope_uuid(raw.get("new_owner_id")),
        new_owner_user_id=parse_scope_uuid(raw.get("new_owner_user_id")),
        new_owner_team_id=parse_scope_uuid(raw.get("new_owner_team_id")),
        old_owner_user_id=parse_scope_uuid(raw.get("old_owner_user_id")),
        old_team_id=parse_scope_uuid(raw.get("old_team_id")),
        resource_id=parse_scope_uuid(raw.get("resource_id")),
        resource_version=_public_revision(raw.get("resource_version")),
        owner_resource_revision=_public_revision(raw.get("owner_resource_revision")),
        quota_revision=_public_revision(raw.get("quota_revision")),
        reservation_revision=_public_revision(raw.get("reservation_revision")),
        runtime_revision=_public_revision(raw.get("runtime_revision")),
        job_version=_public_revision(raw.get("job_version")),
        job_status=_public_text(raw.get("job_status")),
        native_import_version=_public_revision(raw.get("native_import_version")),
        native_project_id=_native_identifier(raw.get("native_project_id")),
        source_file_version=_public_revision(raw.get("source_file_version")),
        source_file_object_id=parse_scope_uuid(raw.get("source_file_object_id")),
        session_version=_public_revision(raw.get("session_version")),
        approved=_public_flag(raw.get("approved")),
        enabled=_public_flag(raw.get("enabled")),
        artifact_confirmed=_public_flag(raw.get("artifact_confirmed")),
        reconciliation_required=_public_flag(raw.get("reconciliation_required")),
        cleanup_required=_public_flag(raw.get("cleanup_required")),
        over_limit=_public_flag(raw.get("over_limit")),
        object_id=_public_text(raw.get("object_id")),
    )


def _scope_identifier(value: UUID | None) -> UUID | None:
    return value if value is not None and value.version == 4 else None


def _public_runtime_audit(details: AuditDetails) -> PublicScopePayload | None:
    if isinstance(details, RuntimeRevisionAudit):
        return PublicScopePayload(
            runtime_revision=_public_revision(details.runtime_revision),
            cleanup_required=details.cleanup_required
            if isinstance(details, RuntimeCleanupRequiredAudit)
            else None,
        )
    if isinstance(details, RuntimeSessionOpenedAudit):
        return PublicScopePayload(runtime_revision=_public_revision(details.runtime_revision))
    if isinstance(details, RuntimeJobRevisionAudit):
        return PublicScopePayload(job_version=_public_revision(details.job_version))
    if isinstance(details, RuntimeJobStatusAudit):
        return PublicScopePayload(
            job_status=_public_text(details.job_status),
            job_version=_public_revision(details.job_version),
        )
    return None


def _public_native_audit(details: AuditDetails) -> PublicScopePayload | None:
    if isinstance(details, NativeImportRevisionAudit):
        return PublicScopePayload(
            native_import_version=_public_revision(details.native_import_version),
            native_project_id=_native_identifier(str(details.native_project_id))
            if isinstance(details, NativeImportDispatchedAudit)
            else None,
            reconciliation_required=details.reconciliation_required
            if isinstance(details, NativeImportReconciliationAudit)
            else None,
        )
    if isinstance(details, NativeImportConfirmedAudit):
        return PublicScopePayload(
            native_project_id=_native_identifier(str(details.native_project_id)),
            native_import_version=_public_revision(details.native_import_version),
            artifact_confirmed=details.artifact_confirmed,
        )
    if isinstance(details, NativeImportReservedAudit):
        return PublicScopePayload(
            native_project_id=_native_identifier(str(details.native_project_id)),
            source_file_version=_public_revision(details.source_file_version),
        )
    if isinstance(details, NativeSourceCleanupAudit):
        return PublicScopePayload(
            source_file_object_id=_scope_identifier(details.source_file_object_id),
            source_file_version=_public_revision(details.source_file_version),
        )
    return None


def _public_audit(details: AuditDetails) -> PublicScopePayload:
    native = _public_native_audit(details)
    if native is not None:
        return native
    runtime = _public_runtime_audit(details)
    if runtime is not None:
        return runtime
    if isinstance(details, FileQuotaRevisionAudit):
        return PublicScopePayload(
            quota_revision=_public_revision(details.quota_revision),
            reservation_revision=_public_revision(details.reservation_revision)
            if isinstance(details, FileQuotaReservationAudit)
            else None,
            over_limit=details.over_limit if isinstance(details, FileQuotaCommittedAudit) else None,
        )
    if isinstance(details, ResourceChangedAudit):
        return PublicScopePayload(
            owner_scope=_public_text(details.owner_scope),
            owner_id=_scope_identifier(details.owner_id),
            resource_id=_scope_identifier(details.resource_id),
            resource_version=_public_revision(details.resource_version),
            owner_resource_revision=_public_revision(details.owner_resource_revision),
        )
    if isinstance(details, LeaseRedemptionAudit):
        return PublicScopePayload(
            owner_scope=_public_text(details.owner_scope),
            owner_id=_scope_identifier(details.owner_id),
        )
    if isinstance(details, ProjectTeamTransferAudit):
        return PublicScopePayload(
            team_id=_scope_identifier(details.team_id),
            old_owner_user_id=_scope_identifier(details.old_owner_user_id),
        )
    if isinstance(details, ProjectPersonalTransferAudit):
        return PublicScopePayload(
            old_team_id=_scope_identifier(details.old_team_id),
            new_owner_user_id=_scope_identifier(details.new_owner_user_id),
        )
    if isinstance(details, ProjectReassignmentAudit):
        return PublicScopePayload(
            new_owner_user_id=_scope_identifier(details.new_owner_user_id),
            new_owner_team_id=_scope_identifier(details.new_owner_team_id),
            old_owner_user_id=_scope_identifier(details.old_owner_user_id),
            old_team_id=_scope_identifier(details.old_team_id),
        )
    if isinstance(details, TeamMemberOwnerAudit):
        return PublicScopePayload(
            team_id=_scope_identifier(details.team_id),
            new_owner_id=_scope_identifier(details.new_owner_id),
        )
    if isinstance(details, TeamMemberAudit):
        return PublicScopePayload(team_id=_scope_identifier(details.team_id))
    if isinstance(details, TeamOwnerAudit):
        return PublicScopePayload(new_owner_id=_scope_identifier(details.new_owner_id))
    if isinstance(details, ConsentAudit):
        return PublicScopePayload(enabled=details.enabled)
    if isinstance(details, ApprovalAudit):
        return PublicScopePayload(approved=details.approved)
    return PublicScopePayload()


def safe_scope_payload(event: AccessOutboxEvent) -> PublicScopePayload:
    if not isinstance(event, LegacySecurityEvent):
        return PublicScopePayload()
    return replace(_public_audit(event.details), object_id=_public_text(str(event.object_id)))


def scope_provenance(event: AccessOutboxEvent) -> ScopeProvenance:
    details = safe_scope_payload(event)
    return ScopeProvenance(
        _scope_identifier(event.project_id),
        details.owner_scope,
        details.owner_id,
        tuple(
            item
            for item in (details.team_id, details.old_team_id, details.new_owner_team_id)
            if item is not None
        ),
        tuple(
            item
            for item in (details.old_owner_user_id, details.new_owner_user_id, details.new_owner_id)
            if item is not None
        ),
        parse_scope_uuid(str(event.object_id)) if isinstance(event, LegacySecurityEvent) else None,
    )
