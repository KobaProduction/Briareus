"""Composition adapter for existing Platform RPC contracts."""

from fastapi import WebSocket

from ._oidc_membership import CurrentPlatformContext
from ._platform_unix_peer import UnixPlatformPeer
from .application.platform_rpc import PlatformRpc
from .domain.platform_management import ManagementIntent, ManagementOutput
from .domain.platform_management import RpcFailure as RpcFailure
from .infrastructure.platform_management import PlatformManagementOwner, PlatformRpcAuthority


class PanelRpc:
    def __init__(
        self, current_context: CurrentPlatformContext, platform: UnixPlatformPeer | None
    ) -> None:
        self.current_context = current_context
        self.platform = platform

    async def platform_call(self, socket: WebSocket, intent: ManagementIntent) -> ManagementOutput:
        owner = PlatformManagementOwner(self.platform) if self.platform is not None else None
        service = PlatformRpc(PlatformRpcAuthority(socket, self.current_context), owner)
        return await service.execute(intent)
