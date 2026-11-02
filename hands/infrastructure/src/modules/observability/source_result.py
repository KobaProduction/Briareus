"""Serialize the concrete public source catalogue at the MCP boundary."""

import json

from mcp.types import CallToolResult, TextContent

from common.account_contracts import AccountPublic, SourceInventoryView
from modules.observability.domain.sources import SourceInventory


def source_result(receipt: SourceInventory) -> CallToolResult:
    payload = SourceInventoryView(
        sources=[
            AccountPublic.model_validate(item, from_attributes=True) for item in receipt.sources
        ],
        count=receipt.count,
    )
    wire = payload.model_dump(mode="json")
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(wire, ensure_ascii=True, allow_nan=False))
        ],
        structured_content=wire,
    )
