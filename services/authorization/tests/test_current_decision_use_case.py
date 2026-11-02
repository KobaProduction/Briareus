"""Request-bound decision proof remains authoritative across owner reads."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

from authorization.application.decisions import ReadCurrentDecision
from authorization.domain.decisions import (
    AuthorizedCurrentGrant,
    DecisionScope,
    VerifiedDecisionCaller,
)


class DecisionRepository:
    def __init__(self, grant: AuthorizedCurrentGrant) -> None:
        self.grant = grant
        self.calls = 0

    async def current_grant(
        self, scope: DecisionScope, caller: VerifiedDecisionCaller
    ) -> AuthorizedCurrentGrant:
        _ = scope, caller
        self.calls += 1
        return self.grant


class CurrentDecisionTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.scope = DecisionScope(uuid4(), uuid4(), "mcp.connect", 3, None)
        self.caller = VerifiedDecisionCaller(
            uuid4(),
            self.scope.project_uuid,
            self.scope.agent_session_uuid,
            "gateway",
            "rauthy",
            "briareus:access",
            datetime.now(UTC) + timedelta(seconds=20),
        )
        self.grant = AuthorizedCurrentGrant(
            self.caller.actor_uuid,
            self.scope.project_uuid,
            self.scope.agent_session_uuid,
            3,
            self.caller.proof_expires_at,
        )

    async def test_mismatched_attested_project_never_queries_owner(self) -> None:
        repository = DecisionRepository(self.grant)
        result = await ReadCurrentDecision(repository).execute(
            self.scope, replace(self.caller, project_uuid=uuid4())
        )
        self.assertIsNone(result)
        self.assertEqual(repository.calls, 0)

    async def test_expired_grant_after_owner_read_is_not_released(self) -> None:
        repository = DecisionRepository(
            replace(self.grant, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        result = await ReadCurrentDecision(repository).execute(self.scope, self.caller)
        self.assertIsNone(result)
        self.assertEqual(repository.calls, 1)

    async def test_exact_current_owner_receipt_is_returned_without_extending_lifetime(self) -> None:
        repository = DecisionRepository(self.grant)
        result = await ReadCurrentDecision(repository).execute(self.scope, self.caller)
        self.assertEqual(result, self.grant)
