"""Common MCP HTTP framing limits; no identity or authorization decision is made here."""

import asyncio
from collections.abc import AsyncIterator, Sequence

from starlette.types import Message, Receive

from node_protocol._mcp_rejection import _McpRejection

MAX_REQUEST_BYTES = 1024 * 1024
MAX_BODY_EVENTS = 1024
BODY_READ_TIMEOUT_SECONDS = 8


class McpBodyRejected(_McpRejection):
    pass


class McpBodyDisconnected(McpBodyRejected):
    def __init__(self) -> None:
        super().__init__("MCP_BODY_INTERRUPTED", 400)


def declared_length(lengths: Sequence[str]) -> int | None:
    if len(lengths) > 1:
        raise McpBodyRejected("MCP_CONTENT_LENGTH_INVALID", 400)
    if not lengths:
        return None
    value = lengths[0]
    if (
        not value.isascii()
        or not value.isdecimal()
        or len(value) > 8
        or (len(value) > 1 and value.startswith("0"))
    ):
        raise McpBodyRejected("MCP_CONTENT_LENGTH_INVALID", 400)
    length = int(value)
    if length > MAX_REQUEST_BYTES:
        raise McpBodyRejected("MCP_BODY_TOO_LARGE", 413)
    return length


def require_encodings(
    transfers: Sequence[str], encodings: Sequence[str], *, has_length: bool
) -> None:
    require_transfer_encoding(transfers, has_length=has_length)
    require_content_encoding(encodings)


def require_transfer_encoding(transfers: Sequence[str], *, has_length: bool) -> None:
    if len(transfers) > 1 or (
        transfers and (transfers[0].strip(" \t\n\r\v\f").casefold() != "chunked" or has_length)
    ):
        raise McpBodyRejected("MCP_TRANSFER_ENCODING_INVALID", 400)


def require_content_encoding(encodings: Sequence[str]) -> None:
    if len(encodings) > 1 or (
        encodings and encodings[0].strip(" \t\n\r\v\f").casefold() != "identity"
    ):
        raise McpBodyRejected("MCP_CONTENT_ENCODING_INVALID", 415)


async def receive_payload(receive: Receive) -> bytes:
    payload = bytearray()
    try:
        async with asyncio.timeout(BODY_READ_TIMEOUT_SECONDS):
            # Count raw messages, including empty chunks suppressed by Request.stream().
            for _ in range(MAX_BODY_EVENTS):
                event = await receive()
                if event.get("type") == "http.disconnect":
                    raise McpBodyDisconnected
                if event.get("type") != "http.request":
                    raise McpBodyRejected("MCP_BODY_UNAVAILABLE", 400)
                chunk = event.get("body", b"")
                if not isinstance(chunk, bytes) or len(chunk) > MAX_REQUEST_BYTES - len(payload):
                    raise McpBodyRejected("MCP_BODY_TOO_LARGE", 413)
                payload.extend(chunk)
                if not event.get("more_body", False):
                    break
            else:
                raise McpBodyRejected("MCP_BODY_TOO_FRAGMENTED", 413)
    except TimeoutError as exc:
        raise McpBodyRejected("MCP_BODY_READ_TIMEOUT", 408) from exc
    return bytes(payload)


async def replay_payload(payload: bytes, receive: Receive) -> AsyncIterator[Message]:
    """Replay verified octets once, then resume the original ASGI receive channel."""
    yield {"type": "http.request", "body": payload, "more_body": False}
    while True:
        yield await receive()
