"""Authenticated Platform agent reads with exact boundary decoding."""

from datetime import datetime
from functools import partial
from uuid import UUID, uuid4

from fastapi import WebSocket
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._platform_unix_peer import UnixPlatformPeer
from control_panel_api.application.agent_directory import AgentQuery
from control_panel_api.domain.agent_directory import AgentDetail, AgentPage, AgentReceipt
from control_panel_api.domain.panel_protocol import PanelContext
from runtime_peer.platform_management_wire import ManagementEnvelope

from ._constructor_bindings import _PeerBinding
from .management_wire import agent_input


class SocketAgentAuthority:
    def __init__(self, socket: WebSocket, current: CurrentPlatformContext) -> None:
        self._socket, self._current = socket, current

    async def current(self, project: UUID) -> PanelContext | None:
        current = await self._current(self._socket, project)
        return None if isinstance(current, JSONResponse) else PanelContext(*current)


class PlatformAgentDirectory(_PeerBinding[UnixPlatformPeer]):
    async def read(
        self, query: AgentQuery, context: PanelContext, deadline: datetime
    ) -> AgentReceipt:
        return await self._peer.management(
            ManagementEnvelope(
                issuer=context.session.issuer,
                subject=context.session.subject,
                operation_uuid=uuid4(),
                action=query.method,
                data=agent_input(query),
            ),
            expires_at=deadline,
            decode=partial(agent_receipt, query.method),
        )


def agent_receipt(method: str, status: int, result: object) -> AgentReceipt:
    if status != 200:
        return AgentReceipt(status)
    if method == "agents.get":
        return AgentReceipt(status, TypeAdapter(AgentDetail).validate_python(result))
    return AgentReceipt(status, TypeAdapter(AgentPage).validate_python(result))
