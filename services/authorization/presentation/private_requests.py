"""Bounded ASGI body adapter before any identity, replay or owner I/O."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import NamedTuple

from fastapi import Request
from starlette.requests import ClientDisconnect
from starlette.types import Message

_MAX_BYTES = 8192


@dataclass(frozen=True, slots=True)
class PrivateRequestBodyRejected(Exception):
    status_code: int
    reason: str


class BoundedPrivateRequest(NamedTuple):
    raw: bytes
    request: Request


def _declared_body_size(request: Request) -> int:
    headers = request.headers
    sizes = headers.getlist("content-length")
    if (
        headers.getlist("content-type") != ["application/json"]
        or headers.getlist("transfer-encoding")
        or headers.getlist("content-encoding")
        or len(sizes) != 1
        or not 1 <= len(sizes[0]) <= 4
        or not sizes[0].isascii()
        or not sizes[0].isdecimal()
        or sizes[0].startswith("0")
    ):
        raise PrivateRequestBodyRejected(422, "ambiguous private Access request framing")
    count = int(sizes[0])
    if count > _MAX_BYTES:
        raise PrivateRequestBodyRejected(413, "private Access request too large")
    return count


async def _read_body(request: Request, count: int) -> bytes:
    body = bytearray()
    try:
        async with asyncio.timeout(5):
            async for part in request.stream():
                if len(part) > _MAX_BYTES - len(body):
                    raise PrivateRequestBodyRejected(413, "private Access request too large")
                body.extend(part)
    except (TimeoutError, RuntimeError, ClientDisconnect):
        raise PrivateRequestBodyRejected(422, "private Access body unavailable") from None
    if not body or len(body) != count:
        raise PrivateRequestBodyRejected(422, "private Access body/length mismatch")
    return bytes(body)


async def _original_messages(request: Request, raw: bytes) -> AsyncIterator[Message]:
    # ASGI's external Message alias is a third-party wire mapping, serialized
    # here directly into Starlette. It never crosses an application port.
    yield {"type": "http.request", "body": raw, "more_body": False}
    while True:
        # Preserve the real disconnect channel after replaying exactly once.
        yield await request.receive()


async def bounded_private_request(request: Request) -> BoundedPrivateRequest:
    count = _declared_body_size(request)
    raw = await _read_body(request, count)
    messages = _original_messages(request, raw)
    return BoundedPrivateRequest(raw, Request(request.scope, receive=messages.__anext__))
