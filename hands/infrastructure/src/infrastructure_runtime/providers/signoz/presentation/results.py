"""Relay provider query documents without making them application entities.

SQL determines result columns at runtime. Its document is decoded only here,
then handed directly to the MCP SDK. No arbitrary document leaves this adapter
as a first-party result contract.
"""

import json

from fastmcp.tools import ToolResult
from mcp.types import CallToolResult, TextContent

from service_runtime.http_transport import HttpTransportResponse


def signoz_result(
    response: HttpTransportResponse, *, provider_native: bool = False
) -> CallToolResult:
    try:
        value: object = json.loads(response.body.decode("utf-8"))
        # Retain the private provider channel's finite-number and text encoding
        # guarantees before allowing the SDK to perform any serialization.
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
    except (ValueError, UnicodeError):
        raise ValueError("SigNoz response is not valid JSON") from None
    if provider_native:
        return CallToolResult(
            content=[TextContent(type="text", text=encoded)],
            structured_content=value if isinstance(value, dict) else None,
            is_error=False,
        )
    # Preserve the standalone SDK's existing result wrapper and metadata.
    result = ToolResult(
        content=[] if value is None else value,
        structured_content={"result": value},
        meta={"fastmcp": {"wrap_result": True}},
    )
    return CallToolResult(
        content=result.content,
        structured_content=result.structured_content,
        meta=result.meta,
        is_error=result.is_error,
    )
