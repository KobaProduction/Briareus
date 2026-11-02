"""Common MCP interface backed by the existing provider dispatch and admission."""

from collections.abc import Awaitable, Callable

from mcp.types import CallToolRequestParams, CallToolResult

from service_runtime.runtime_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL
from source_control.providers.github.contracts import ToolRegistrar

from .contracts import SourceCapabilities, SourceTarget
from .requests import SourceRequest, capabilities, legacy_call


def register_source_control_tools(
    mcp: ToolRegistrar,
    execute: Callable[[CallToolRequestParams], Awaitable[CallToolResult]],
) -> None:
    @mcp.tool(title="Source Control", annotations=DESTRUCTIVE_EXTERNAL)
    async def source_control(
        request: SourceRequest, account_id: str | None = None
    ) -> CallToolResult:
        """Invoke a supported operation using the selected provider's exact parameters.

        account_id selects the original account and is null only for list_accounts.
        Results and errors retain the provider operation's existing contract. Source mutations
        and local Git remain subject to the current provider policy and project authority.
        Retained replies name the original provider operation; poll/cancel with that tool
        and the same account_id. Its existing operation grant remains required.
        """
        return await execute(legacy_call(request, account_id))

    @mcp.tool(title="Source Control capabilities", annotations=READ_EXTERNAL)
    def source_control_capabilities(target: SourceTarget) -> SourceCapabilities:
        """List common operations for a target; this observation grants no access.

        Provider-specific review, workflow and account tools retain their existing names.
        For retained capability calls, pass target as provider when polling.
        """
        return capabilities(target)
