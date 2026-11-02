"""Bounded private transport; raw SDK data never enters the execution scenario."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from mcp.types import CallToolRequestParams, CallToolResult, TextContent
from pydantic import TypeAdapter
from pydantic_core import PydanticSerializationError

from runtime_peer.terminal_receipts import TerminalReceipt
from terminal_hand.application.worker_contracts import WorkerOutcome
from terminal_hand.infrastructure.worker_messages import (
    MAX_PRIVATE_WORKER_BYTES,
    PrivateWorkerCommand,
    TerminalReply,
)

_RESULT = TypeAdapter[TerminalReceipt](TerminalReceipt)


def decode_command(line: bytes) -> PrivateWorkerCommand:
    if len(line) > MAX_PRIVATE_WORKER_BYTES or not line.endswith(b"\n"):
        raise ValueError("Supervisor command exceeds worker budget")
    command = PrivateWorkerCommand.model_validate_json(line)
    if command.human is None and len(line) > 65536:
        raise ValueError("Agent command exceeds existing worker budget")
    return command


def _encode(reply: TerminalReply) -> str:
    return json.dumps(
        reply.model_dump(mode="json", by_alias=True, exclude_none=True),
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def encode_outcome(correlation: UUID, outcome: WorkerOutcome) -> str:
    if outcome.error is not None:
        return _encode(TerminalReply(id=correlation, error=outcome.error))
    try:
        if outcome.result is None:
            raise ValueError("Typed Terminal receipt required")
        result = _RESULT.dump_python(outcome.result, mode="json")
        wire = CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, allow_nan=False))],
            structured_content=result,
            is_error=False,
        )
        encoded = _encode(TerminalReply(id=correlation, result=wire))
    except (PydanticSerializationError, TypeError, ValueError):
        return _encode(TerminalReply(id=correlation, error="TERMINAL_OPERATION_FAILED"))
    if len(encoded.encode("ascii")) > 1_000_000:
        return _encode(TerminalReply(id=correlation, error="TERMINAL_OUTPUT_LIMIT"))
    return encoded


@dataclass(frozen=True, slots=True)
class BoundWorkerDispatch:
    call: Callable[[CallToolRequestParams], Awaitable[TerminalReceipt]]
    request: CallToolRequestParams

    async def execute(self) -> TerminalReceipt:
        return await self.call(self.request)
