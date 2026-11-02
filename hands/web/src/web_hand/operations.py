"""Explicit bounded background interface for the original Web MCP tools."""

from fastmcp import FastMCP
from mcp.types import CallToolResult

from hand_runtime.presentation.deferred_operations import register_deferred_start


def register_operations[AppState](mcp: FastMCP[AppState]) -> None:
    register_deferred_start(
        mcp,
        name="web_operation_start",
        description="""Start one long original local/external Web tool after browser preparation.

Use local_browser_status until running=true before starting. Retain
operation_id and tool from the response, then call web_operation_poll
every two seconds. Each poll needs current rights for the original
tool as well as start/poll. Without fresh authority native processes
pause within five seconds. Only one operation runs per placement.
Never blindly retry a start whose response was lost. A worker restart
interrupts its operations; old IDs never replay an effect.""",
        reason="Metadata only; trusted supervisor executes",
    )

    @mcp.tool(output_schema=None)
    async def web_operation_poll(operation_id: str, tool: str) -> CallToolResult:
        """Continue an owned operation and return its state and original result.

        Pass the exact tool returned by start. The supervisor independently
        matches it to the stored operation before renewing execution authority.
        Lost start reply: operation_id="request:<original start request UUID>"
        resolves the original handle without replay.
        Another actor, AgentSession or grant revision cannot resume or read it.
        """
        del operation_id, tool
        raise RuntimeError("Metadata only; trusted supervisor executes")

    @mcp.tool(output_schema=None)
    async def web_operation_cancel(operation_id: str) -> CallToolResult:
        """Stop an owned native operation without resuming it or rolling back effects.

        Browser processes stop and metadata prepares again; persistent browser
        profiles and project files remain. Other MCP placements are unaffected.
        """
        del operation_id
        raise RuntimeError("Metadata only; trusted supervisor executes")
