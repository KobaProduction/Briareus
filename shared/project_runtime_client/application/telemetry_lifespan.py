"""Forward the host SDK state unchanged while adding the telemetry lifecycle."""

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import overload


@overload
def with_runtime_telemetry[Application](
    original: Callable[[Application], AbstractAsyncContextManager[None]],
    telemetry: Callable[[], AbstractAsyncContextManager[None]],
) -> Callable[[Application], AbstractAsyncContextManager[None]]: ...


@overload
def with_runtime_telemetry[Application, State: Mapping[str, object]](
    original: Callable[[Application], AbstractAsyncContextManager[State]],
    telemetry: Callable[[], AbstractAsyncContextManager[None]],
) -> Callable[[Application], AbstractAsyncContextManager[State]]: ...


def with_runtime_telemetry[Application, State](
    original: Callable[[Application], AbstractAsyncContextManager[State]],
    telemetry: Callable[[], AbstractAsyncContextManager[None]],
) -> Callable[[Application], AbstractAsyncContextManager[State]]:
    # The overloads preserve Starlette's two distinct state shapes. State is
    # retained parametrically: mapping values are neither parsed nor erased.
    @asynccontextmanager
    async def lifecycle(active: Application) -> AsyncIterator[State]:
        async with original(active) as state, telemetry():
            yield state

    return lifecycle
