"""Worker lifecycle ordering while forwarding the host SDK's state unchanged."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import Protocol, overload


class WorkerLifecycle(Protocol):
    async def warmup(self) -> None: ...
    async def watchdog(self) -> None: ...
    async def close(self) -> None: ...


@overload
def managed_lifespan[Application](
    sdk_lifespan: Callable[[Application], AbstractAsyncContextManager[None]],
    worker: WorkerLifecycle,
    prepare: Callable[[], Awaitable[None]],
    probe: Callable[[], Awaitable[None]],
) -> Callable[[Application], AbstractAsyncContextManager[None]]: ...


@overload
def managed_lifespan[Application, State: Mapping[str, object]](
    sdk_lifespan: Callable[[Application], AbstractAsyncContextManager[State]],
    worker: WorkerLifecycle,
    prepare: Callable[[], Awaitable[None]],
    probe: Callable[[], Awaitable[None]],
) -> Callable[[Application], AbstractAsyncContextManager[State]]: ...


def managed_lifespan[Application, State](
    sdk_lifespan: Callable[[Application], AbstractAsyncContextManager[State]],
    worker: WorkerLifecycle,
    prepare: Callable[[], Awaitable[None]],
    probe: Callable[[], Awaitable[None]],
) -> Callable[[Application], AbstractAsyncContextManager[State]]:
    @asynccontextmanager
    async def lifespan(current: Application) -> AsyncIterator[State]:
        watchdog: asyncio.Task[None] | None = None
        try:
            await prepare()
            await worker.warmup()
            watchdog = asyncio.create_task(worker.watchdog())
            async with sdk_lifespan(current) as state:
                await probe()
                yield state
        finally:
            if watchdog is not None:
                watchdog.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog
            await worker.close()

    return lifespan
