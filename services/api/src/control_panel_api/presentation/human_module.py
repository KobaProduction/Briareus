"""Decode one browser-owned request before consulting authority or dispatching tools."""

from uuid import UUID

from control_panel_api.application.module_contracts import ModuleRequest
from control_panel_api.domain.module_preparation import ModuleTarget
from control_panel_api.domain.platform_management import RpcFailure
from control_panel_api.infrastructure.module_commands import MODULE_COMMANDS


def module_request(method: str, params: object, target: ModuleTarget) -> ModuleRequest:
    try:
        if not isinstance(params, dict):
            raise ValueError("Module request object required")
        if method == target.prefix + ".resources":
            if set(params) != {"project_uuid"} or not isinstance(params["project_uuid"], str):
                raise ValueError("Exact project request required")
            project = UUID(params["project_uuid"])
            if project.version != 4:
                raise ValueError("Project UUIDv4 required")
            return ModuleRequest(project, None)
        command = MODULE_COMMANDS[target.module].model_validate(params)
        if command.tool not in target.tools | target.controls:
            raise ValueError("Unsupported human tool")
        return ModuleRequest(command.project_uuid, command)
    except (ValueError, KeyError, TypeError):
        raise RpcFailure(target.prefix.upper() + "_COMMAND_INVALID") from None
