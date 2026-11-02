"""Start the engine before its bridge; an incomplete startup leaves no native cohort."""

from typing import Protocol

from service_runtime.runtime_binding import _RuntimeBinding


class NativeRuntime(Protocol):
    async def start_engine(self) -> None: ...
    async def await_engine(self) -> None: ...
    async def start_bridge(self) -> None: ...
    async def await_bridge(self) -> None: ...
    async def close(self) -> None: ...


class StartNativeRuntime(_RuntimeBinding[NativeRuntime]):
    async def execute(self) -> None:
        try:
            await self.runtime.start_engine()
            await self.runtime.await_engine()
            await self.runtime.start_bridge()
            await self.runtime.await_bridge()
        except BaseException:
            await self.runtime.close()
            raise
