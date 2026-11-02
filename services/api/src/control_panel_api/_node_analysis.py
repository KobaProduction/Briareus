"""Human analysis controls retain provider credentials and current Gateway admission."""

from fastapi import WebSocket

from runtime_peer import PeerClient

from ._node_browser import human_module_call
from ._oidc_membership import CurrentPlatformContext
from .application.module_contracts import ModuleRequest
from .infrastructure.module_replies import NativeModuleReply
from .presentation.module_targets import ANALYSIS_TARGET

TOOLS = ANALYSIS_TARGET.tools


async def analysis_call(
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
        target=ANALYSIS_TARGET,
    )
