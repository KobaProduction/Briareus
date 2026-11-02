"""Serialize typed use-case receipts only at the MCP response boundary."""

import json

from mcp.types import CallToolResult, TextContent

from files_hand.application.workspace_ports import FileToolReceipt
from files_hand.presentation.receipt_models import file_receipt


def file_result(result: FileToolReceipt) -> CallToolResult:
    payload = file_receipt(result).model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, allow_nan=False))],
        structured_content=payload,
        is_error=False,
    )
