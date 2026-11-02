"""Keep merge and optional local-cleanup fields at their original MCP positions."""

import json
from dataclasses import asdict

from mcp.types import CallToolResult, TextContent

from .application.merge import LocalWorktreeCleanup, MergeReceipt


def merge_result(receipt: MergeReceipt) -> CallToolResult:
    payload = asdict(receipt)
    if (
        isinstance(receipt.local_cleanup, LocalWorktreeCleanup)
        and receipt.local_cleanup.status is None
    ):
        payload["local_cleanup"].pop("status")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=False,
    )
