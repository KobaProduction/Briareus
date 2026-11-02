"""Perform owner IO while preserving proof freshness and typed failures."""

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from .approval_contracts import (
    OwnerManagementConflict,
    OwnerManagementDenied,
    OwnerManagementInvalidInput,
    OwnerManagementNotFound,
)


class ApprovalFailureCode(Enum):
    PROOF_EXPIRED = "PLATFORM_PROOF_EXPIRED"
    DENIED = "APPROVAL_PERMISSION_DENIED"
    NOT_FOUND = "AGENT_SESSION_NOT_FOUND"
    CONFLICT = "APPROVAL_REVISION_CONFLICT"
    INVALID_SCOPE = "APPROVAL_SCOPE_INVALID"
    UNAVAILABLE = "APPROVAL_OWNER_UNAVAILABLE"
    INVALID_RECEIPT = "APPROVAL_OWNER_INVALID_RESPONSE"
    INVALID_SESSION_RECEIPT = "AGENT_SESSION_OWNER_INVALID_RESPONSE"
    INVALID_SESSION = "AGENT_SESSION_INVALID"
    INVALID_LABEL = "AGENT_SESSION_LABEL_INVALID"


@dataclass(frozen=True, slots=True)
class ApprovalFailure:
    code: ApprovalFailureCode


def expired_or_not_found(expires_at: datetime) -> ApprovalFailure:
    code = (
        ApprovalFailureCode.PROOF_EXPIRED
        if expires_at <= datetime.now(UTC)
        else ApprovalFailureCode.NOT_FOUND
    )
    return ApprovalFailure(code)


async def execute_owner[Result](
    call: Awaitable[Result],
    *,
    expires_at: datetime,
) -> Result | ApprovalFailure:
    """Never retain owner results after the independently bounded proof expires."""
    try:
        outcome = await call
    except OwnerManagementDenied:
        return ApprovalFailure(ApprovalFailureCode.DENIED)
    except OwnerManagementNotFound:
        return expired_or_not_found(expires_at)
    except OwnerManagementConflict:
        return ApprovalFailure(ApprovalFailureCode.CONFLICT)
    except OwnerManagementInvalidInput:
        return ApprovalFailure(ApprovalFailureCode.INVALID_SCOPE)
    except Exception:
        # An owner may fail for any transport reason. No provider text crosses the port.
        return ApprovalFailure(ApprovalFailureCode.UNAVAILABLE)
    if expires_at <= datetime.now(UTC):
        return ApprovalFailure(ApprovalFailureCode.PROOF_EXPIRED)
    return outcome
