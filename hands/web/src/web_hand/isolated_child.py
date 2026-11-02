"""Composition root for isolated Web/DevTools/Playwright MCP execution."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from fastmcp import Client

from .infrastructure.child_browser import announce, relay
from .infrastructure.isolation import read_browser_privileges
from .node_runtime import BrowserRuntime, create_runtime


def require_child_isolation() -> None:
    read_browser_privileges().require_child()


async def close_runtime(runtime: BrowserRuntime) -> None:
    with suppress(Exception):
        await runtime.external.disconnect()
    with suppress(Exception):
        await runtime.devtools._disconnect()
    runtime.devtools._stderr_forwarder.close()
    with suppress(Exception):
        await runtime.browser._stop_runtime(stop_display=True)


async def main() -> None:
    require_child_isolation()
    runtime = create_runtime()
    try:
        async with Client(runtime.mcp, timeout=None) as client:
            allowed = await announce(client)
            await relay(client, runtime, allowed)
    finally:
        await close_runtime(runtime)


if __name__ == "__main__":
    asyncio.run(main())
