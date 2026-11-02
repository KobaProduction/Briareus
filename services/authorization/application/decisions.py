"""Revalidate the original identity proof before and after current owner I/O."""

from datetime import UTC, datetime
from typing import Protocol

from authorization.domain.decisions import (
    AuthorizedCurrentGrant,
    DecisionScope,
    VerifiedDecisionCaller,
)
from service_runtime._repository_binding import _RepositoryBinding


class CurrentDecisionRepositoryPort(Protocol):
    async def current_grant(
        self,
        scope: DecisionScope,
        caller: VerifiedDecisionCaller,
    ) -> AuthorizedCurrentGrant | None: ...


class ReadCurrentDecision(_RepositoryBinding[CurrentDecisionRepositoryPort]):
    async def execute(
        self, scope: DecisionScope, caller: VerifiedDecisionCaller
    ) -> AuthorizedCurrentGrant | None:
        if not caller.matches(scope, datetime.now(UTC)):
            return None
        grant = await self.repository.current_grant(scope, caller)
        # A transaction exit/commit may block after policy evaluation.
        if grant is None or grant.expires_at <= datetime.now(UTC):
            return None
        return grant
