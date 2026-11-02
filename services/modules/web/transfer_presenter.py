"""Only the outer MCP presenter flattens typed transfer results to the deployed wire shape."""

import json
from dataclasses import asdict

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel as BaseModel

from modules.web.models import BrowserDownload
from modules.workspace_compat.domain.receipts import WorkspaceEntry
from web_runtime.presentation.browser_tools import present_browser as present_browser


def present_browser_transfer(result: WorkspaceEntry | BrowserDownload) -> CallToolResult:
    if isinstance(result, BrowserDownload):
        payload = asdict(result.file)
        payload["suggested_filename"] = result.suggested_filename
    else:
        payload = asdict(result)
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False))
        ],
        structured_content=payload,
    )
