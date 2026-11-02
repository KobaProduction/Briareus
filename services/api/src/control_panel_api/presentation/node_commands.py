"""Validate deployed Node RPC shapes before entering application dispatch."""

from uuid import uuid4

from pydantic import ValidationError

from control_panel_api.application.node_contracts import NodeInput
from control_panel_api.domain.platform_management import RpcFailure


def node_command(method: str, params: object) -> NodeInput:
    try:
        if not isinstance(params, dict):
            raise ValueError("Node request object required")
        if method == "nodes.inventory":
            if set(params) != {"project_uuid"}:
                raise ValueError
            return NodeInput.model_validate(
                {
                    "project_uuid": params["project_uuid"],
                    "operation_uuid": uuid4(),
                    "action": "list",
                }
            )
        value = NodeInput.model_validate(params)
        if value.action == "list":
            raise ValueError
        return value
    except (ValueError, ValidationError):
        raise RpcFailure("NODE_COMMAND_INVALID") from None
