"""Bounded private pipe I/O without granting or renewing process authority."""

import asyncio
import time


async def exchange_bytes(
    child: asyncio.subprocess.Process | None,
    payload: bytes,
    *,
    expires_at: float,
    background: bool,
    pipes_failure: str,
    expired_failure: str,
) -> bytes:
    if child is None or child.stdin is None or child.stdout is None:
        raise ValueError(pipes_failure)
    # Background IPC still depends on the owner's independently running UID watchdog.
    async with asyncio.timeout(None if background else max(0, expires_at - time.time())):
        child.stdin.write(payload)
        await child.stdin.drain()
        raw = await child.stdout.readline()
    if not background and expires_at <= time.time():
        raise ValueError(expired_failure)
    return raw
