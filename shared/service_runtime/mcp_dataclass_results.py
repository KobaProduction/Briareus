"""Serialize dataclass receipts once at an MCP presentation boundary."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from mcp.types import CallToolResult, TextContent

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def dataclass_result(receipt: DataclassInstance) -> CallToolResult:
    payload = asdict(receipt)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=False,
    )
