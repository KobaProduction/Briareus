"""Authority lifetime and receipt policies independent of the HTTP framework."""

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from control_panel_api.application.approval_contracts import (
    OwnerManagementConflict,
    OwnerManagementDenied,
    OwnerManagementNotFound,
)
from control_panel_api.application.approval_execution import (
    ApprovalFailure,
    ApprovalFailureCode,
    execute_owner,
)
from control_panel_api.domain.approval_policy import ApprovalLifecycle, SessionState


async def successful_owner() -> str:
    return "trusted receipt"


async def missing_owner() -> str:
    raise OwnerManagementNotFound


async def denied_owner() -> str:
    raise OwnerManagementDenied


async def conflicted_owner() -> str:
    raise OwnerManagementConflict


class OwnerExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_cannot_outlive_browser_bounded_platform_proof(self) -> None:
        expired = datetime.now(UTC) - timedelta(seconds=1)
        result = await execute_owner(successful_owner(), expires_at=expired)
        self.assertEqual(result, ApprovalFailure(ApprovalFailureCode.PROOF_EXPIRED))

    async def test_missing_session_does_not_override_expired_proof(self) -> None:
        expired = datetime.now(UTC) - timedelta(seconds=1)
        result = await execute_owner(missing_owner(), expires_at=expired)
        self.assertEqual(result, ApprovalFailure(ApprovalFailureCode.PROOF_EXPIRED))

    async def test_owner_denial_and_cas_conflict_keep_their_authority(self) -> None:
        expired = datetime.now(UTC) - timedelta(seconds=1)
        denied = await execute_owner(denied_owner(), expires_at=expired)
        conflict = await execute_owner(conflicted_owner(), expires_at=expired)
        self.assertEqual(denied, ApprovalFailure(ApprovalFailureCode.DENIED))
        self.assertEqual(conflict, ApprovalFailure(ApprovalFailureCode.CONFLICT))

    async def test_current_proof_preserves_real_missing_and_success(self) -> None:
        current = datetime.now(UTC) + timedelta(seconds=30)
        missing = await execute_owner(missing_owner(), expires_at=current)
        success = await execute_owner(successful_owner(), expires_at=current)
        self.assertEqual(missing, ApprovalFailure(ApprovalFailureCode.NOT_FOUND))
        self.assertEqual(success, "trusted receipt")


class ReceiptInvariantTests(unittest.TestCase):
    def test_requester_cannot_resolve_own_approval(self) -> None:
        requester, parent, issued = uuid4(), uuid4(), uuid4()
        lifecycle = ApprovalLifecycle("approved", requester, parent, requester, issued)
        self.assertFalse(lifecycle.valid())

    def test_elevated_grant_must_be_distinct_from_parent(self) -> None:
        requester, resolver, parent = uuid4(), uuid4(), uuid4()
        lifecycle = ApprovalLifecycle("approved", requester, parent, resolver, parent)
        self.assertFalse(lifecycle.valid())

    def test_revocation_hint_requires_current_approver_and_active_session(self) -> None:
        now = datetime.now(UTC)
        state = SessionState(
            "active", False, "requestable", now + timedelta(seconds=10), ("revoke",)
        )
        self.assertTrue(state.valid(now=now, approver=True))
        self.assertFalse(state.valid(now=now, approver=False))
        self.assertFalse(state.valid(now=now + timedelta(seconds=11), approver=True))

    def test_expired_state_cannot_claim_future_expiry(self) -> None:
        now = datetime.now(UTC)
        state = SessionState("expired", True, "requestable", now + timedelta(seconds=10), ())
        self.assertFalse(state.valid(now=now, approver=True))
