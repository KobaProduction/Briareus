"""Serialize concrete Hand arguments into the existing MCP SDK call envelope."""

from mcp_types import CallToolRequestParams

from runtime_peer.analysis_arguments import AnalysisNativeArguments

from .module_commands import NativeToolCommand


def tool_parameters(command: NativeToolCommand) -> CallToolRequestParams:
    arguments = command.arguments
    if isinstance(arguments, AnalysisNativeArguments):
        return CallToolRequestParams(
            name=command.tool,
            arguments={
                "engine": arguments.engine,
                "tool": arguments.call.name,
                "arguments": arguments.call.arguments,
            },
        )
    return CallToolRequestParams(name=command.tool, arguments=arguments.model_dump(mode="json"))
