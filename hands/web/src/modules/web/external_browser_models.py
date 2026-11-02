"""Explicit external provider observations, serialized at the MCP boundary."""

from mcp.types import CallToolResult

from common.browser_contracts import ExternalBrowserStatus as ExternalBrowserStatus


def present_external_status(status: ExternalBrowserStatus) -> CallToolResult:
    return CallToolResult(
        content=[],
        structured_content=status.model_dump(mode="json", exclude_unset=True),
    )
