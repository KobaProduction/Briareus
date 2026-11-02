"""Existing Identity security notifications, without credential material."""

from uuid import UUID

from pydantic import TypeAdapter

from common.infrastructure.owner_event_records import OwnerMutationEvent
from identity.application.account_receipts import AccountRevisionReceipt
from identity.infrastructure.audit_records import AccountSecurityAudit


class AccountOperationEvent(AccountRevisionReceipt):
    operation_uuid: UUID


type IdentityEvent = (
    OwnerMutationEvent | AccountSecurityAudit | AccountRevisionReceipt | AccountOperationEvent
)

IDENTITY_EVENT = TypeAdapter[IdentityEvent](IdentityEvent)
