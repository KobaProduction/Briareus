"""Decode owner-specific RPC commands and preserve their existing failure semantics."""

from typing import Literal

from control_panel_api.application.panel_commands import FacadeCommand
from control_panel_api.domain.panel_protocol import MODULE_METHODS, PLATFORM_METHODS, RpcFault
from control_panel_api.domain.platform_management import RpcFailure

from .directory_queries import agent_query
from .human_module import module_request
from .module_targets import module_target
from .node_commands import node_command
from .platform_commands import management_rpc_intent


def _facade_command(method: str, params: object) -> FacadeCommand | Literal["unavailable"]:
    if method in MODULE_METHODS:
        return module_request(method, params, module_target(method))
    if method in PLATFORM_METHODS:
        return management_rpc_intent(method, params)
    if method in {"agents.list", "agents.get"}:
        try:
            return agent_query(method, params)
        except ValueError:
            raise RpcFailure("AGENT_QUERY_INVALID") from None
    if method in {"nodes.inventory", "nodes.command"}:
        return node_command(method, params)
    return "unavailable"


def decode_facade_command(
    method: str, params: object
) -> FacadeCommand | RpcFault | Literal["unavailable"]:
    try:
        return _facade_command(method, params)
    except RpcFailure as failure:
        uncertain = None if method in {"agents.list", "agents.get"} else failure.uncertain
        return RpcFault(failure.code, uncertain=uncertain)
