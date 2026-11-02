"""Bind current socket/proof callbacks to the existing module owner facades."""

from dataclasses import dataclass, field
from typing import Protocol

from fastapi import WebSocket

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._panel_rpc import PanelRpc, RpcFailure
from control_panel_api._platform_unix_peer import UnixPlatformPeer
from control_panel_api.application.module_contracts import ModuleRequest
from control_panel_api.application.node_contracts import NodeInput
from control_panel_api.application.panel_channel import RpcFault, RpcPayload, RpcValue
from control_panel_api.application.panel_commands import RpcRequest
from control_panel_api.domain.agent_directory import AgentQuery
from control_panel_api.domain.panel_protocol import MODULE_METHODS, PLATFORM_METHODS
from control_panel_api.domain.platform_management import ManagementIntent, ManagementOutput
from control_panel_api.infrastructure.module_replies import NativeModuleReply, NativeToolReply
from runtime_peer import PeerClient


class ModuleCall(Protocol):
    async def __call__(
        self,
        *,
        socket: WebSocket,
        request: ModuleRequest,
        current_context: CurrentPlatformContext,
        resources: PeerClient | None,
    ) -> NativeModuleReply: ...


class PlatformCalls(Protocol):
    async def platform_call(
        self, socket: WebSocket, intent: ManagementIntent
    ) -> ManagementOutput: ...


def module_call(method: str) -> ModuleCall:
    if method.startswith("browser."):
        from control_panel_api._node_browser import browser_call

        return browser_call
    if method.startswith("terminal."):
        from control_panel_api._node_terminal import terminal_call

        return terminal_call
    if method.startswith("files."):
        from control_panel_api._node_files import files_call

        return files_call
    from control_panel_api._node_analysis import analysis_call

    return analysis_call


@dataclass(slots=True)
class PanelFacadeAdapter:
    socket: WebSocket
    current_context: CurrentPlatformContext
    platform: UnixPlatformPeer | None
    resources: PeerClient | None
    rpc: PlatformCalls = field(init=False)

    def __post_init__(self) -> None:
        self.rpc = PanelRpc(self.current_context, self.platform)

    async def call(self, request: RpcRequest) -> RpcValue[RpcPayload[NativeToolReply]] | RpcFault:
        if isinstance(request.command, RpcFault):
            return request.command
        try:
            return await self.dispatch(request)
        except RpcFailure as failure:
            message = failure.code
            uncertain = failure.uncertain
            if request.method in {"agents.list", "agents.get"}:
                return RpcFault(message)
            return RpcFault(message, uncertain=uncertain)

    async def dispatch(self, request: RpcRequest) -> RpcValue[RpcPayload[NativeToolReply]]:
        if request.method in PLATFORM_METHODS:
            return RpcValue(
                await self.rpc.platform_call(self.socket, request.command_as(ManagementIntent))
            )
        if request.method in MODULE_METHODS:
            return RpcValue(
                await module_call(request.method)(
                    socket=self.socket,
                    request=request.command_as(ModuleRequest),
                    current_context=self.current_context,
                    resources=self.resources,
                )
            )
        if request.method in {"agents.list", "agents.get"}:
            from control_panel_api._node_agents import agents_call

            handler = agents_call
            return RpcValue(
                await handler(
                    socket=self.socket,
                    query=request.command_as(AgentQuery),
                    current_context=self.current_context,
                    platform=self.platform,
                )
            )
        from control_panel_api._node_rpc import node_call

        node_handler = node_call
        return RpcValue(
            await node_handler(
                socket=self.socket,
                command=request.command_as(NodeInput),
                current_context=self.current_context,
                resources=self.resources,
            )
        )
