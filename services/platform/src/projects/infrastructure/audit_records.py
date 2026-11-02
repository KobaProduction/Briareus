"""Platform SQL audit schemas reuse existing management and invitation receipts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter

from common.infrastructure.audit_records import OperationAudit, TeamOperationAudit
from projects.domain.user_links import PlatformRole
from projects.infrastructure.panel_journal import InvitationEvidence, ManagementEvidence


class RauthyUserLinkedAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str
    subject: str
    role: PlatformRole
    source: Literal["rauthy-users-read"] = "rauthy-users-read"


class FirstOperatorAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Literal["independent-operator-approval"] = "independent-operator-approval"


class FirstOperatorWorkspaceAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    owner_user_id: UUID


type PlatformAudit = (
    OperationAudit
    | TeamOperationAudit
    | RauthyUserLinkedAudit
    | FirstOperatorAudit
    | FirstOperatorWorkspaceAudit
    | ManagementEvidence
    | InvitationEvidence
)

PLATFORM_AUDIT = TypeAdapter[PlatformAudit](PlatformAudit)
