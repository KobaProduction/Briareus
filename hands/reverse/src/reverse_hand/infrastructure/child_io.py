"""Bounded private stdin/stdout adapter; SDK result serialization stays at this edge."""

import asyncio
import json
import sys
import time
from collections.abc import Callable

from mcp.types import CallToolResult, TextContent

from reverse_hand.application.dispatch import RejectedResult
from reverse_hand.infrastructure.analysis_requests import current_request
from reverse_hand.infrastructure.engine_dispatch import AnalysisIngress


async def serve_requests(
    dispatch: AnalysisIngress,
    names: frozenset[str],
    runtime_ready: Callable[[], bool],
) -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline, 32769)
        if not line:
            return
        if len(line) > 32768:
            raise ValueError("Bounded supervisor input required")
        request = current_request(line, names, time.time(), runtime_ready=runtime_ready())
        outcome = await dispatch.execute(request)
        rejected = isinstance(outcome, RejectedResult)
        result = (
            CallToolResult(
                content=[TextContent(type="text", text=outcome.reason)],
                is_error=True,
            )
            if isinstance(outcome, RejectedResult)
            else outcome
        )
        fields = {"content", "is_error"}
        if not rejected:
            fields.add("structured_content")
        if result.meta is not None:
            fields.add("meta")
        reply = json.dumps(
            {
                "id": str(request.request_uuid),
                "result": result.model_dump(mode="json", by_alias=True, include=fields),
            },
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(reply.encode()) > 1_000_000:
            raise ValueError("Bounded Analysis result required")
        print(reply, flush=True)
