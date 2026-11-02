"""Compose human module use cases with current authority and real public MCP transport."""

from fastapi import WebSocket

from runtime_peer import PeerClient

from ._oidc_membership import CurrentPlatformContext
from .application.human_module import HumanModule, McpInvocation
from .application.module_contracts import ModuleRequest
from .domain.module_preparation import ModuleTarget
from .infrastructure.human_module import (
    HumanMcpSessions,
    ModuleScopes,
    SocketCredentials,
    SocketModuleAuthority,
)
from .infrastructure.module_replies import NativeModuleReply
from .presentation.module_targets import BROWSER_TARGET

TOOLS = BROWSER_TARGET.tools
CONTROLS = BROWSER_TARGET.controls


async def browser_call(
    *,
    socket: WebSocket,
    request: ModuleRequest,
    current_context: CurrentPlatformContext,
    resources: PeerClient | None,
) -> NativeModuleReply:
    return await human_module_call(
        socket=socket,
        request=request,
        current_context=current_context,
        resources=resources,
        target=BROWSER_TARGET,
    )


async def human_module_call(
    *,
    socket: WebSocket,
    request: ModuleRequest,
    current_context: CurrentPlatformContext,
    resources: PeerClient | None,
    target: ModuleTarget,
) -> NativeModuleReply:
    credentials = SocketCredentials(socket, prefix=target.prefix)
    service = HumanModule(
        SocketModuleAuthority(socket, current_context),
        ModuleScopes(resources) if resources is not None else None,
        credentials,
        McpInvocation(HumanMcpSessions(credentials)),
    )
    return await service.execute(target, request)
