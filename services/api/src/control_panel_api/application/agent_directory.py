"""Read directory data only while the original project authority remains current."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from control_panel_api.domain.agent_directory import AgentDirectory, AgentReceipt
from control_panel_api.domain.agent_directory import AgentQuery as AgentQuery
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import RpcFailure


class AgentAuthority(Protocol):
    async def current(self, project: UUID) -> PanelContext | None: ...


class AgentDirectoryOwner(Protocol):
    async def read(
        self, query: AgentQuery, context: PanelContext, deadline: datetime
    ) -> AgentReceipt: ...


class ReadAgentDirectory:
    def __init__(self, authority: AgentAuthority, owner: AgentDirectoryOwner | None) -> None:
        self._authority, self._owner = authority, owner

    async def execute(self, query: AgentQuery) -> AgentDirectory:
        original = await self._authority.current(query.project)
        if original is None:
            raise RpcFailure("AGENT_PROJECT_ACCESS_REQUIRED")
        if self._owner is None:
            raise RpcFailure("AGENT_OWNER_UNAVAILABLE")
        deadline = min(original.session.expires_at, original.proof.expires_at)
        if deadline <= datetime.now(UTC):
            raise RpcFailure("AGENT_PROJECT_ACCESS_REQUIRED")
        try:
            receipt = await self._owner.read(query, original, deadline)
        except Exception:
            raise RpcFailure("AGENT_OWNER_UNAVAILABLE") from None
        if receipt.status != 200 or receipt.directory is None:
            raise RpcFailure(
                {403: "AGENT_PROJECT_ACCESS_REQUIRED", 404: "AGENT_NOT_FOUND"}.get(
                    receipt.status, "AGENT_OWNER_UNAVAILABLE"
                )
            )
        fresh = await self._authority.current(query.project)
        if not self._continues(original, fresh, deadline):
            raise RpcFailure("AGENT_PROJECT_ACCESS_REQUIRED")
        return receipt.directory

    @staticmethod
    def _continues(original: PanelContext, fresh: PanelContext | None, deadline: datetime) -> bool:
        return (
            fresh is not None
            and fresh.proof.user_uuid == original.proof.user_uuid
            and fresh.session.subject == original.session.subject
            and fresh.session.issuer == original.session.issuer
            and min(deadline, fresh.session.expires_at, fresh.proof.expires_at) > datetime.now(UTC)
        )
