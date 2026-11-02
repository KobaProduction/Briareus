"""Bound MCP HTTP framing before the independent coarse Cedar decision."""

from starlette.requests import Request

from node_protocol.json_boundary import mcp_json_is_object
from node_protocol.mcp_http import McpBodyRejected as McpBodyRejected
from node_protocol.mcp_http import declared_length as declared_length
from node_protocol.mcp_http import receive_payload as receive_mcp_payload
from node_protocol.mcp_http import require_encodings as require_mcp_encodings


def require_encodings(request: Request, *, has_length: bool) -> None:
    require_mcp_encodings(
        request.headers.getlist("transfer-encoding"),
        request.headers.getlist("content-encoding"),
        has_length=has_length,
    )


async def receive_payload(request: Request) -> bytes:
    return await receive_mcp_payload(request.receive)


async def read_mcp_body(request: Request) -> bytes:
    """Validate bounded UTF-8 JSON object and return original octets intact."""
    lengths = request.headers.getlist("content-length")
    length = declared_length(lengths)
    require_encodings(request, has_length=bool(lengths))
    payload = await receive_payload(request)
    if length is not None and len(payload) != length:
        raise McpBodyRejected("MCP_CONTENT_LENGTH_INVALID", 400)
    try:
        if not mcp_json_is_object(payload):
            raise McpBodyRejected("MCP_BATCH_NOT_SUPPORTED", 400)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise McpBodyRejected("MCP_INVALID_JSON", 400) from exc
    return payload
