"""Require current exact-project access before and after reading agents."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._authority_bindings import _ReadAuthorityBinding
from projects.domain.agents import AgentDetail, AgentItem, AgentPage
from projects.domain.management import ManagementError


@dataclass(frozen=True, slots=True)
class AgentQuery:
    issuer: str
    subject: str
    actor_uuid: UUID
    project_uuid: UUID
    agent_uuid: UUID | None = None
    cursor: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ManagementError(422, "AGENT_QUERY_INVALID")


class AgentReader(Protocol):
    async def get(self, project_uuid: UUID, agent_uuid: UUID) -> AgentItem | None: ...
    async def page(self, query: AgentQuery) -> tuple[AgentItem, ...]: ...


class AgentProjectAuthority(Protocol):
    async def require_current(self, query: AgentQuery) -> None: ...


class ReadAgents(_ReadAuthorityBinding[AgentReader, AgentProjectAuthority]):
    async def execute(self, query: AgentQuery, deadline: datetime) -> AgentDetail | AgentPage:
        await self._authority.require_current(query)
        result: AgentDetail | AgentPage
        if query.agent_uuid is not None:
            item = await self._reader.get(query.project_uuid, query.agent_uuid)
            if item is None:
                raise ManagementError(404, "AGENT_NOT_FOUND")
            result = AgentDetail(item)
        else:
            rows = await self._reader.page(query)
            items = rows[: query.limit]
            more = len(rows) > query.limit
            result = AgentPage(items, more, items[-1].id if more else None)
        await self._authority.require_current(query)
        if deadline <= self._now():
            raise ManagementError(403, "AGENT_AUTHORITY_EXPIRED")
        return result
