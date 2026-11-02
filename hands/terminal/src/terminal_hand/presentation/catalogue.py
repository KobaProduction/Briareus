"""Install original SDK metadata without executing privileged tool closures."""

from collections.abc import Callable
from copy import deepcopy

from fastmcp import FastMCP

from hand_runtime.tool_binding import bind_delegated_tool
from node_protocol.terminal import TOOLS
from terminal_hand.presentation.node_tool import NodeTerminalTool
from terminal_hand.worker_server import TerminalSupervisor


async def install_node_tools(
    mcp: FastMCP[None],
    template: FastMCP[None],
    supervisor: TerminalSupervisor,
    network_check: Callable[[], None] | None,
) -> None:
    metadata = await template.list_tools()
    if {tool.name for tool in metadata} != TOOLS:
        raise ValueError("Terminal tool catalogue differs from authority contract")
    for tool in metadata:
        parameters = deepcopy(tool.parameters)
        bounded = {"job_read": ("wait_seconds", 0), "job_wait": ("timeout_seconds", 3)}.get(
            tool.name
        )
        if bounded:
            field, default = bounded
            parameters["properties"][field].update(default=default, minimum=0, maximum=3)
        runner = NodeTerminalTool(tool.name, supervisor, network_check)
        bounded_tool = tool.model_copy(update={"parameters": parameters})
        mcp.add_tool(bind_delegated_tool(bounded_tool, runner.run))
