"""Validate owned browser payloads while the SDK retains protocol metadata."""

import json

from mcp_types import CallToolResult
from pydantic import TypeAdapter

from runtime_peer.browser_receipts import (
    BROWSER_RESULTS,
    BrowserOperationReceipt,
    BrowserOperationState,
    BrowserPreparingReceipt,
    BrowserReceipt,
    BrowserStatus,
)

_OPERATION_TOOLS = frozenset({"web_operation_start", "web_operation_poll", "web_operation_cancel"})
_STATUS = TypeAdapter[BrowserStatus | BrowserPreparingReceipt](
    BrowserStatus | BrowserPreparingReceipt
)


def browser_payload(encoded: str, tool: str) -> BrowserReceipt | BrowserPreparingReceipt:
    if tool == "local_browser_status":
        return _STATUS.validate_json(encoded)
    return BROWSER_RESULTS[tool].model_validate_json(encoded)


def browser_reply(reply: CallToolResult, tool: str) -> CallToolResult:
    if tool not in BROWSER_RESULTS and tool not in _OPERATION_TOOLS:
        raise ValueError("Owned browser tool required")
    content = reply.structured_content
    if content is None:
        return reply
    encoded = json.dumps(content, ensure_ascii=False, allow_nan=False)
    if tool in BROWSER_RESULTS:
        receipt = browser_payload(encoded, tool)
        return reply.model_copy(update={"structured_content": receipt})
    operation = BrowserOperationReceipt[BrowserOperationState, CallToolResult].model_validate_json(
        encoded
    )
    if operation.tool not in BROWSER_RESULTS:
        if tool == "web_operation_cancel":
            return reply
        raise ValueError("Owned original browser tool required")
    if operation.result is not None:
        operation = operation.model_copy(
            update={"result": browser_reply(operation.result, operation.tool)}
        )
    return reply.model_copy(update={"structured_content": operation})
