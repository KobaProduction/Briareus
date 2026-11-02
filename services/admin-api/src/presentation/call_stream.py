"""Retained calls SSE framing and connection-scoped cursor lifetime."""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from application.invocation_contracts import InvocationDocument
from domain.telemetry import Invocation


class CallStreamSource(Protocol):
    async def recent(self, *, limit: int = 100) -> Sequence[Invocation]: ...


class StreamConnection(Protocol):
    async def is_disconnected(self) -> bool: ...


def _invocation_frame(invocation: Invocation) -> str:
    payload = json.dumps(
        InvocationDocument(root=invocation).model_dump(mode="json"), ensure_ascii=False
    )
    return f"data: {payload}\n\n"


async def stream_calls(audit: CallStreamSource, connection: StreamConnection) -> AsyncIterator[str]:
    seen: set[str] = set()
    initial = await audit.recent(limit=100)
    for item in reversed(initial):
        seen.add(item.id)
        yield _invocation_frame(item)
    while not await connection.is_disconnected():
        latest = await audit.recent(limit=100)
        fresh = [item for item in reversed(latest) if item.id not in seen]
        for item in fresh:
            seen.add(item.id)
            yield _invocation_frame(item)
        if len(seen) > 5000:
            seen = {item.id for item in latest}
        yield ": keepalive\n\n"
        await asyncio.sleep(1)
