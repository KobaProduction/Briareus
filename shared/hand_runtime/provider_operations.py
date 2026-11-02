"""Provider continuations require the exact original account selection on every poll."""

from fastmcp import FastMCP
from mcp.types import CallToolResult


def register_provider_operations[AppState](mcp: FastMCP[AppState], module: str) -> None:
    @mcp.tool(name=module + "_operation_start", output_schema=None)
    async def start(tool: str, arguments: dict[str, object]) -> CallToolResult:
        """Start one long original provider tool.

        Poll every two seconds with the handle, exact tool and original account_id.
        Start/poll need original-tool rights; processes pause without fresh Core
        authority. Never replay a start after a lost reply.
        """
        del tool, arguments
        raise RuntimeError("Metadata only")

    @mcp.tool(name=module + "_operation_poll", output_schema=None)
    async def poll(
        operation_id: str, tool: str, account_id: str | None = None, provider: str | None = None
    ) -> CallToolResult:
        """Resume an owned operation using the exact original tool/account_id.

        Use null account_id for account-list tools. Current tool+start+poll rights
        are required. Changed actor/session/revision/account cannot resume it.
        If the start reply was lost, request:<original start request UUID> resolves
        its handle without replay.
        """
        del operation_id, tool, account_id, provider
        raise RuntimeError("Metadata only")

    @mcp.tool(name=module + "_operation_cancel", output_schema=None)
    async def cancel(
        operation_id: str, tool: str, account_id: str | None = None, provider: str | None = None
    ) -> CallToolResult:
        """Stop an owned operation without resuming it.

        Pass the exact original tool/account_id. Existing external effects are
        not rolled back.
        """
        del operation_id, tool, account_id, provider
        raise RuntimeError("Metadata only")
