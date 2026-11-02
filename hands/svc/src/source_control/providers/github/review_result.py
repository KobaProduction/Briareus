"""Present gate receipts in the deployed flat MCP shape."""

import json
from dataclasses import asdict

from mcp.types import CallToolResult, TextContent

from .application.review_gates import (
    CheckRunsReceipt,
    RequiredChecksReceipt,
    RequiredReviewsReceipt,
)


def review_result(
    receipt: CheckRunsReceipt | RequiredChecksReceipt | RequiredReviewsReceipt,
) -> CallToolResult:
    payload = asdict(receipt)
    if isinstance(receipt, RequiredReviewsReceipt) and receipt.head_sha is None:
        payload.pop("head_sha")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=False,
    )
