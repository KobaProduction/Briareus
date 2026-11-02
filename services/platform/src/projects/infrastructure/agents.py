"""Agent SQL directory and existing exact-project projection adapter."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from agents._persistence import AgentIdentityRow
from common.platform_db import PlatformDatabase
from projects._oidc_membership_projection import CurrentRauthyPlatformMembership
from projects.application.agents import AgentQuery
from projects.domain.agents import AgentItem
from projects.domain.management import ManagementError
from projects.infrastructure._projection_binding import _ProjectionBinding
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding


class ProjectProjection(Protocol):
    async def resolve_project(
        self,
        *,
        issuer: str,
        subject: str,
        project_uuid: UUID,
    ) -> CurrentRauthyPlatformMembership | None: ...


class ProjectionAgentAuthority(_ProjectionBinding[ProjectProjection]):
    async def require_current(self, query: AgentQuery) -> None:
        current = await self._projection.resolve_project(
            issuer=query.issuer,
            subject=query.subject,
            project_uuid=query.project_uuid,
        )
        if (
            current is None
            or current.user_id != query.actor_uuid
            or current.expires_at <= datetime.now(UTC)
        ):
            raise ManagementError(403, "AGENT_PROJECT_ACCESS_REQUIRED")
        if not any(
            item.project_id == query.project_uuid and "use_resources" in item.permissions
            for item in current.projects
        ):
            raise ManagementError(403, "AGENT_PROJECT_ACCESS_REQUIRED")


class SqlAgentReader(_PrivateDatabaseBinding[PlatformDatabase]):
    async def get(self, project_uuid: UUID, agent_uuid: UUID) -> AgentItem | None:
        async with self._database.transaction() as tx:
            row = await tx.scalar(
                select(AgentIdentityRow).where(
                    AgentIdentityRow.project_id == project_uuid,
                    AgentIdentityRow.id == agent_uuid,
                )
            )
            return None if row is None else agent_item(row)

    async def page(self, query: AgentQuery) -> tuple[AgentItem, ...]:
        statement = select(AgentIdentityRow).where(
            AgentIdentityRow.project_id == query.project_uuid
        )
        if query.cursor is not None:
            statement = statement.where(AgentIdentityRow.id > query.cursor)
        async with self._database.transaction() as tx:
            rows = await tx.scalars(statement.order_by(AgentIdentityRow.id).limit(query.limit + 1))
            return tuple(agent_item(row) for row in rows)


def agent_item(row: AgentIdentityRow) -> AgentItem:
    return AgentItem(
        row.id,
        row.project_id,
        row.parent_agent_id,
        row.name,
        row.enabled,
        row.created_at.isoformat(),
    )
