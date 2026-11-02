"""Fresh Access-owner SQL and Cedar adapter for request-bound grant reads."""

from datetime import UTC, datetime

from sqlalchemy import select

from authorization._access_cedar import permits_current_project_grant
from authorization._resource_scope import EffectResource
from authorization._session_persistence import ProjectAgentSessionRow
from authorization.domain.decisions import (
    AuthorizedCurrentGrant,
    DecisionScope,
    VerifiedDecisionCaller,
)
from common.platform_db import PlatformDatabase
from service_runtime.platform_db_mechanics import _DatabaseBinding


class SqlCurrentDecisionRepository(_DatabaseBinding[PlatformDatabase]):
    async def current_grant(
        self, scope: DecisionScope, caller: VerifiedDecisionCaller
    ) -> AuthorizedCurrentGrant | None:
        async with self.database.transaction() as tx:
            row = await tx.scalar(
                select(ProjectAgentSessionRow).where(
                    ProjectAgentSessionRow.session_uuid == scope.agent_session_uuid,
                    ProjectAgentSessionRow.project_id == scope.project_uuid,
                )
            )
            if caller.proof_expires_at <= datetime.now(UTC):
                return None
            if row is None or not self._permits(row, scope, caller):
                return None
            return AuthorizedCurrentGrant(
                caller.actor_uuid,
                row.project_id,
                row.session_uuid,
                row.version,
                min(caller.proof_expires_at, row.hard_expires_at),
            )

    @staticmethod
    def _permits(
        row: ProjectAgentSessionRow, scope: DecisionScope, caller: VerifiedDecisionCaller
    ) -> bool:
        effect = scope.effect
        return permits_current_project_grant(
            row=row,
            actor_uuid=caller.actor_uuid,
            project_uuid=scope.project_uuid,
            operation=scope.action,
            expected_version=scope.expected_grant_revision,
            hand=effect.hand if effect is not None else None,
            tool=effect.tool if effect is not None else None,
            resource=EffectResource(kind=effect.resource_kind, id=effect.resource_id)
            if effect is not None
            else None,
        )
