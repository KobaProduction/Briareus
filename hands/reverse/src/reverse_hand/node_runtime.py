"""Composition of the private Ghidra lifecycle and pinned process adapter."""

from pathlib import Path

from .application.native_runtime import StartNativeRuntime
from .infrastructure.ghidra_runtime import GhidraProcesses


class GhidraRuntime:
    def __init__(self, root: Path, memory_bytes: int) -> None:
        self.processes = GhidraProcesses(root, memory_bytes)
        self.start_runtime = StartNativeRuntime(self.processes)

    async def start(self) -> None:
        await self.start_runtime.execute()

    def current(self) -> bool:
        return self.processes.current()

    async def wait_stopped(self) -> None:
        await self.processes.wait_stopped()

    async def close(self) -> None:
        await self.processes.close()
