"""Transport-only call outcome; never store arguments, results or credentials."""
import asyncio
import json
import logging
import time

LOG = logging.getLogger(__name__)


def outcome(status, body, complete):
    if status >= 400:
        return "failed"
    if not complete or body is None:
        return "unknown"
    try:
        frames = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith(b"data:")]
        value = frames[-1] if frames else json.loads(body)
        if not isinstance(value, dict) or not isinstance(value.get("result"), dict):
            return "failed" if isinstance(value, dict) and "error" in value else "unknown"
        return "failed" if value["result"].get("isError") is True else "completed"
    except (ValueError, TypeError):
        return "unknown"


def observer(authority, permit, *, started):
    async def record(status, body, complete):
        try:
            async with asyncio.timeout(2):
                await authority.record_call(permit=permit, status=outcome(status, body, complete),
                    duration_ms=min(86400000, round((time.monotonic() - started) * 1000)))
        except Exception:
            # Losing diagnostics cannot replay or turn an executed effect into
            # an execution failure. The actual reply remains unchanged.
            LOG.warning("MCP call journal delivery unavailable")
    return record
