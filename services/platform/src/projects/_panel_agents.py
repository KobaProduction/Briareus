"""Panel input adaptation and composition for the exact-project agent directory."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from common.platform_db import PlatformDatabase
from projects._oidc_membership_projection import CurrentRauthyPlatformMembership
from projects.application.agents import AgentQuery, ReadAgents
from projects.domain.agents import AgentDetail, AgentPage
from projects.domain.management import ManagementError
from projects.infrastructure.agents import (
    ProjectionAgentAuthority,
    ProjectProjection,
    SqlAgentReader,
)
from projects.presentation.management_inputs import AgentGetQuery, AgentListQuery


class AgentService(Protocol):
    @property
    def db(self) -> PlatformDatabase: ...

    @property
    def projection(self) -> ProjectProjection: ...


def canonical_id(value: object) -> UUID:
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise ManagementError(422, "AGENT_IDENTIFIER_INVALID") from None


def agent_query(query: AgentGetQuery | AgentListQuery, actor_uuid: UUID) -> AgentQuery:
    if isinstance(query, AgentGetQuery):
        return AgentQuery(
            query.issuer,
            query.subject,
            actor_uuid,
            canonical_id(query.data.project_uuid),
            canonical_id(query.data.id),
        )
    return AgentQuery(
        query.issuer,
        query.subject,
        actor_uuid,
        canonical_id(query.data.project_uuid),
        None,
        canonical_id(query.data.cursor) if query.data.cursor is not None else None,
        query.data.limit,
    )


async def read_agents(
    service: AgentService,
    query: AgentGetQuery | AgentListQuery,
    actor: CurrentRauthyPlatformMembership,
    deadline: datetime,
) -> AgentDetail | AgentPage:
    use_case = ReadAgents(
        SqlAgentReader(service.db),
        ProjectionAgentAuthority(service.projection),
        lambda: datetime.now(UTC),
    )
    return await use_case.execute(agent_query(query, actor.user_id), deadline)
