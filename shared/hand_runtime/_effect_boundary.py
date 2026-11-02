"""Bounded MCP protocol preflight before upstream SDK and real identity checks.

This adapter never authenticates callers or grants tools. The SDK and Cedar
middleware retain authority; original HTTP bytes are replayed unchanged.
"""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from node_protocol.json_boundary import mcp_json_is_object
from node_protocol.mcp_http import (
    McpBodyDisconnected,
    McpBodyRejected,
    declared_length,
    receive_payload,
    replay_payload,
    require_content_encoding,
    require_transfer_encoding,
)


def _headers(scope: Scope) -> Headers:
    raw = scope.get("headers", [])
    for name, value in raw:
        if not isinstance(name, bytes) or not isinstance(value, bytes):
            raise McpBodyRejected("MCP_HTTP_HEADERS_INVALID", 400)
        if b"\x00" in value or b"\r" in value or b"\n" in value:
            raise McpBodyRejected("MCP_HTTP_HEADERS_INVALID", 400)
    return Headers(raw=[(name.lower(), value) for name, value in raw])


def _ascii_values(headers: Headers, name: str, code: str, status: int) -> list[str]:
    values = headers.getlist(name)
    if any(not value.isascii() for value in values):
        raise McpBodyRejected(code, status)
    return values


def _require_content_type(headers: Headers) -> None:
    values = _ascii_values(headers, "content-type", "MCP_CONTENT_TYPE_INVALID", 415)
    if len(values) != 1:
        raise McpBodyRejected("MCP_CONTENT_TYPE_INVALID", 415)
    media_type, separator, params = values[0].casefold().partition(";")
    if media_type.strip() != "application/json" or (
        separator and params.strip() != "charset=utf-8"
    ):
        raise McpBodyRejected("MCP_CONTENT_TYPE_INVALID", 415)


def _header_preflight(scope: Scope) -> int | None:
    """Validate direct Hand headers independently of server normalization."""
    headers = _headers(scope)
    _require_content_type(headers)
    lengths = headers.getlist("content-length")
    length = declared_length(lengths)
    require_transfer_encoding(
        _ascii_values(headers, "transfer-encoding", "MCP_TRANSFER_ENCODING_INVALID", 400),
        has_length=bool(lengths),
    )
    require_content_encoding(
        _ascii_values(headers, "content-encoding", "MCP_CONTENT_ENCODING_INVALID", 415)
    )
    return length


async def _validated_payload(scope: Scope, receive: Receive) -> bytes:
    length = _header_preflight(scope)
    payload = await receive_payload(receive)
    if length is not None and len(payload) != length:
        raise McpBodyRejected("MCP_CONTENT_LENGTH_INVALID", 400)
    try:
        object_root = mcp_json_is_object(payload)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise McpBodyRejected("MCP_INVALID_JSON", 400) from exc
    if not object_root:
        raise McpBodyRejected("MCP_BATCH_NOT_SUPPORTED", 400)
    return payload


class EffectBoundary:
    """Preserve exact SDK lifespan/HostOrigin middleware and request bytes."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self._app(scope, receive, send)
            return
        if scope.get("raw_path") != b"/mcp" or scope.get("query_string", b"") != b"":
            await self._deny(scope, receive, send, "MCP_RESOURCE_PATH_INVALID", 404)
            return
        if scope.get("method") != "POST":
            await self._app(scope, receive, send)
            return
        try:
            payload = await _validated_payload(scope, receive)
        except McpBodyDisconnected:
            return
        except McpBodyRejected as error:
            # Send after the total read timeout has ended; never emit two responses.
            await self._deny(scope, receive, send, error.code, error.status_code)
            return
        events = replay_payload(payload, receive)
        await self._app(scope, events.__anext__, send)

    @staticmethod
    async def _deny(scope: Scope, receive: Receive, send: Send, code: str, status: int) -> None:
        response = JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": code}},
            status_code=status,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
        await response(scope, receive, send)
