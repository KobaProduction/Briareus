"""Concrete Access audit facts and the two existing outbox document formats."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, TypeAdapter, field_validator

from authorization.domain.owner_events import EventCall
from common.audit_payloads import (
    FileQuotaCommittedAudit,
    FileQuotaConfiguredAudit,
    FileQuotaReservationAudit,
    FileQuotaReservedAudit,
    FileQuotaRevisionAudit,
    NativeImportConfirmedAudit,
    NativeImportDispatchedAudit,
    NativeImportReconciliationAudit,
    NativeImportReservedAudit,
    NativeImportRevisionAudit,
    NativeProjectRegisteredAudit,
    NativeSourceCleanupAudit,
    ResourceChangedAudit,
    RuntimeCleanupOwnerAudit,
    RuntimeCleanupRequiredAudit,
    RuntimeJobRevisionAudit,
    RuntimeJobStatusAudit,
    RuntimeOwnerInstanceAudit,
    RuntimeRevisionAudit,
    RuntimeSessionJobAudit,
    RuntimeSessionOpenedAudit,
)
from common.infrastructure.audit_records import OperationAudit, UserRoleAudit
from runtime_peer.identifiers import preserved_identifier


class AuditFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NoAuditDetails(AuditFact):
    """An event intentionally has no auxiliary facts; every extra key is rejected."""


class ConsentAudit(AuditFact):
    enabled: StrictBool


class ServiceKeyAudit(AuditFact):
    service_id: UUID
    audience: str


class ServiceKeyRegisteredAudit(ServiceKeyAudit):
    version: StrictInt


class ServiceOperationAudit(ServiceKeyAudit):
    operation: str


class LeaseRedemptionAudit(AuditFact):
    lease_id: UUID
    owner_scope: str
    owner_id: UUID


class LeaseIssuedAudit(LeaseRedemptionAudit):
    kind: str


class ProjectTeamTransferAudit(AuditFact):
    team_id: UUID
    old_owner_user_id: UUID


class ProjectPersonalTransferAudit(AuditFact):
    old_team_id: UUID
    new_owner_user_id: UUID


class ProjectReassignmentAudit(AuditFact):
    new_owner_user_id: UUID | None
    new_owner_team_id: UUID | None
    old_owner_user_id: UUID | None
    old_team_id: UUID | None


class AgentRevisionAudit(AuditFact):
    agent_version: StrictInt


class ApprovalAudit(AuditFact):
    approved: StrictBool


class TeamMemberAudit(AuditFact):
    team_id: UUID


class TeamOwnerAudit(AuditFact):
    new_owner_id: UUID


class TeamMemberOwnerAudit(TeamMemberAudit):
    new_owner_id: UUID


class McpCallAudit(OperationAudit):
    call: EventCall


type AuditDetails = (
    NoAuditDetails
    | NativeProjectRegisteredAudit
    | NativeImportReservedAudit
    | NativeImportRevisionAudit
    | NativeImportDispatchedAudit
    | NativeImportConfirmedAudit
    | NativeImportReconciliationAudit
    | NativeSourceCleanupAudit
    | ResourceChangedAudit
    | FileQuotaCommittedAudit
    | FileQuotaConfiguredAudit
    | FileQuotaReservedAudit
    | FileQuotaReservationAudit
    | FileQuotaRevisionAudit
    | RuntimeCleanupOwnerAudit
    | RuntimeCleanupRequiredAudit
    | RuntimeJobRevisionAudit
    | RuntimeJobStatusAudit
    | RuntimeOwnerInstanceAudit
    | RuntimeRevisionAudit
    | RuntimeSessionJobAudit
    | RuntimeSessionOpenedAudit
    | McpCallAudit
    | OperationAudit
    | ConsentAudit
    | UserRoleAudit
    | ServiceKeyRegisteredAudit
    | ServiceOperationAudit
    | ServiceKeyAudit
    | LeaseIssuedAudit
    | LeaseRedemptionAudit
    | ProjectTeamTransferAudit
    | ProjectPersonalTransferAudit
    | ProjectReassignmentAudit
    | AgentRevisionAudit
    | ApprovalAudit
    | TeamMemberOwnerAudit
    | TeamMemberAudit
    | TeamOwnerAudit
)


class AccessMutationEvent(AuditFact):
    operation_uuid: UUID
    project_id: UUID
    entity_id: UUID


class LegacySecurityEvent(AuditFact):
    actor_id: UUID | None
    project_id: UUID | None
    object_id: UUID | str
    details: AuditDetails

    object_locator = field_validator("object_id", mode="before")(staticmethod(preserved_identifier))


type AccessOutboxEvent = AccessMutationEvent | LegacySecurityEvent

AUDIT_DETAILS = TypeAdapter[AuditDetails](AuditDetails)
ACCESS_OUTBOX_EVENT = TypeAdapter[AccessOutboxEvent](AccessOutboxEvent)
