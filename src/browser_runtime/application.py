"""Typed lifecycle boundary for the persistent browser process."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class BrowserProcessState:
    running: bool
    pid: int | None
    manually_stopped: bool


class BrowserProcessPort(Protocol):
    def state(self) -> BrowserProcessState: ...

    async def start(self) -> None: ...

    async def stop(self, *, force: bool = False) -> None: ...


class BrowserLifecycle:
    def __init__(self, process: BrowserProcessPort) -> None:
        self.process = process

    async def execute(self, action: Literal["start", "stop", "restart"]) -> BrowserProcessState:
        if action in {"stop", "restart"}:
            await self.process.stop(force=action == "stop")
        if action in {"start", "restart"}:
            await self.process.start()
        return self.process.state()
