"""Node management composition over the existing authenticated Panel WebSocket."""

from fastapi import WebSocket

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._panel_events import panel_events
from control_panel_api.application.node_contracts import NodeInput as NodeInput
from control_panel_api.application.node_contracts import NodeOutput
from control_panel_api.application.node_management import ManageNodes
from control_panel_api.infrastructure.agent_directory import SocketAgentAuthority
from control_panel_api.infrastructure.node_management import NodeCommittedEvents, ResourcesNodes
from control_panel_api.presentation.node_commands import node_command as node_command
from runtime_peer import PeerClient


async def node_call(
    *,
    socket: WebSocket,
    command: NodeInput,
    current_context: CurrentPlatformContext,
    resources: PeerClient | None,
) -> NodeOutput:
    service = ManageNodes(
        SocketAgentAuthority(socket, current_context),
        ResourcesNodes(resources) if resources is not None else None,
        NodeCommittedEvents(panel_events),
    )
    return await service.execute(command)
