"""UID1000 composition root for pinned Serena MCP stdio and LSP processes."""

from __future__ import annotations

import asyncio
import os

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from .infrastructure.child_relay import announce, relay, require_isolation
from .runtime import prepare_project, server_parameters


async def main() -> None:
    require_isolation()
    project = prepare_project(os.environ["BRIAREUS_SERENA_PROJECT_PATH"])
    os.chdir(project)
    with await asyncio.to_thread(open, os.devnull, "w") as diagnostics:
        async with (
            stdio_client(server_parameters(project), errlog=diagnostics) as (read, write),
            ClientSession(read, write) as session,
        ):
            names = await announce(session)
            await relay(session, project, names)


if __name__ == "__main__":
    asyncio.run(main())
