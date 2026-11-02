"""Serialize concrete merge-request results only at the MCP boundary."""

from mcp.types import CallToolResult, TextContent

from source_control.providers.gitlab.merge_receipts import MergeRequestReceipt


def merge_request_result(receipt: MergeRequestReceipt) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=receipt.model_dump_json(by_alias=True))],
        structured_content=receipt.model_dump(mode="json", by_alias=True),
    )
