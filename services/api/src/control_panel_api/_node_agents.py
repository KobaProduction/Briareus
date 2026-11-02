"""Composition for read-only human AgentIdentity views."""

from fastapi import WebSocket

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._platform_unix_peer import UnixPlatformPeer
from control_panel_api.application.agent_directory import ReadAgentDirectory
from control_panel_api.domain.agent_directory import AgentDirectory, AgentQuery
from control_panel_api.infrastructure.agent_directory import (
    PlatformAgentDirectory,
    SocketAgentAuthority,
)


async def agents_call(
    *,
    socket: WebSocket,
    query: AgentQuery,
    current_context: CurrentPlatformContext,
    platform: UnixPlatformPeer | None,
) -> AgentDirectory:
    service = ReadAgentDirectory(
        SocketAgentAuthority(socket, current_context),
        PlatformAgentDirectory(platform) if platform is not None else None,
    )
    return await service.execute(query)
