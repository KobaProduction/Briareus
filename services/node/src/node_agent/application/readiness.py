"""Bounded readiness waits observe native state without restarting processes."""

import asyncio
from typing import Protocol

from node_agent.domain.readiness import ProcessState


class ReadinessRuntime(Protocol):
    async def state(self, container: str) -> ProcessState: ...

    async def complete(self, container: str) -> bool: ...


class ReadinessFailed(RuntimeError):
    def __init__(self, state: ProcessState) -> None:
        super().__init__("Target failed readiness")
        self.state = state


class WaitReady:
    def __init__(self, runtime: ReadinessRuntime) -> None:
        self._runtime = runtime

    async def execute(self, container: str) -> None:
        # CPU-throttled cold imports need the existing full startup allowance.
        async with asyncio.timeout(180):
            while True:
                state = await self._runtime.state(container)
                if state.failed:
                    raise ReadinessFailed(state)
                if state.health == "healthy" and await self._runtime.complete(container):
                    return
                await asyncio.sleep(1)
