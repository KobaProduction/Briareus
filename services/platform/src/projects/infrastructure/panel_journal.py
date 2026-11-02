"""Models for the existing versioned management and invitation JSONB journals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from projects.domain.management import ManagementOutcome

if TYPE_CHECKING:
    from projects._control_ledger import OwnerAuditRow

MANAGEMENT_REVISION = "panel-management-v1"
INVITATION_REVISION = "panel-invitations-v1"


class JournalValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManagementReceipt(JournalValue):
    id: UUID
    name: StrictStr

    @classmethod
    def from_record(cls, value: ManagementOutcome) -> ManagementReceipt:
        return cls(id=value.id, name=value.name)

    def record(self) -> ManagementOutcome:
        return ManagementOutcome(self.id, self.name)


class JournalEvidence(JournalValue):
    fingerprint: StrictStr


class ManagementEvidence(JournalEvidence):
    outcome: ManagementReceipt

    @classmethod
    def load(cls, row: OwnerAuditRow) -> ManagementEvidence:
        if row.owner_revision != MANAGEMENT_REVISION:
            raise ValueError("Unknown management journal schema")
        if not isinstance(row.details, cls):
            raise ValueError("Management journal record required")
        return row.details


class InviterReceipt(JournalValue):
    id: UUID
    enabled: StrictBool
    state: Literal["committed"] = "committed"


class InvitationReceipt(JournalValue):
    id: StrictStr
    state: Literal["provider_created"] = "provider_created"
    delivery: Literal["unconfirmed"] = "unconfirmed"


class InvitationPending(JournalValue):
    state: Literal["issuing"] = "issuing"


type InvitationJournalOutcome = Annotated[
    InviterReceipt | InvitationReceipt | InvitationPending, Field(discriminator="state")
]


class InvitationEvidence(JournalEvidence):
    outcome: InvitationJournalOutcome
    email: StrictStr | None = None
    enabled: StrictBool | None = None

    @classmethod
    def load(cls, row: OwnerAuditRow) -> InvitationEvidence:
        if row.owner_revision != INVITATION_REVISION:
            raise ValueError("Unknown invitation journal schema")
        if not isinstance(row.details, cls):
            raise ValueError("Invitation journal record required")
        return row.details
