"""Credential-free Identity audit records for existing account lifecycle events."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter

from common.infrastructure.audit_records import OperationAudit


class AccountSecurityAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    subject_user_id: UUID
    credential_version: StrictInt = Field(ge=0)


class UserDeletedAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    recipient_user_id: UUID


type IdentityAudit = OperationAudit | AccountSecurityAudit | UserDeletedAudit

IDENTITY_AUDIT = TypeAdapter[IdentityAudit](IdentityAudit)
