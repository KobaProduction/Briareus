"""Decoded Panel commands, composed from their existing owner-specific contracts."""

from dataclasses import dataclass
from typing import Literal

from control_panel_api.domain.agent_directory import AgentQuery
from control_panel_api.domain.panel_protocol import HistorySelection, RpcFault, TopicSelection
from control_panel_api.domain.platform_management import ManagementIntent

from .module_contracts import ModuleRequest
from .node_contracts import NodeInput

type FacadeCommand = ModuleRequest | ManagementIntent | AgentQuery | NodeInput
type PanelCommand = (
    FacadeCommand | TopicSelection | HistorySelection | RpcFault | Literal["empty", "unavailable"]
)


@dataclass(frozen=True, slots=True)
class RpcRequest:
    identifier: str
    method: str
    command: PanelCommand

    def command_as[CommandT](self, expected: type[CommandT]) -> CommandT:
        if isinstance(self.command, expected):
            return self.command
        raise ValueError("Panel method requires its decoded command")
