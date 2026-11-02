"""A fenced controller leaves process restart to its runtime supervisor."""

import asyncio
from typing import Protocol


class ControllerServer(Protocol):
    should_exit: bool

    async def serve(self) -> None: ...


async def serve_controller(server: ControllerServer, lost: asyncio.Event) -> None:
    serving = asyncio.create_task(server.serve())
    lease = asyncio.create_task(lost.wait())
    try:
        done, _ = await asyncio.wait({serving, lease}, return_when=asyncio.FIRST_COMPLETED)
        if lease in done:
            server.should_exit = True
        await serving
    finally:
        for task in (serving, lease):
            task.cancel()
        await asyncio.gather(serving, lease, return_exceptions=True)
