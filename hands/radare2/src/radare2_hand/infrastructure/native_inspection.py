"""Keep process execution and engine-owned response documents outside use cases."""

import asyncio
from typing import Protocol

from radare2_hand.application.inspection import InspectBinary
from radare2_hand.domain.commands import NativeCommand


class NativeRunner(Protocol):
    async def run(self, arguments: list[str], deadline: float | None) -> bytes: ...


class NativeInspection:
    def __init__(self, prepare: InspectBinary, runner: NativeRunner, lock: asyncio.Lock) -> None:
        self.prepare, self.runner, self.lock = prepare, runner, lock

    async def invoke(self, command: NativeCommand, deadline: float | None) -> bytes:
        # Verification and the native read retain the same exclusion against
        # imports/deletes; no unverified path can reach the process driver.
        async with self.lock:
            prepared = self.prepare.prepare(command)
            return await self.runner.run(
                [
                    "-2",
                    "-q",
                    "-NN",
                    "-S",
                    "-e",
                    "scr.color=0",
                    "-e",
                    "scr.interactive=false",
                    "-e",
                    "bin.demangle=false",
                    "-c",
                    prepared.command.command,
                    prepared.path,
                ],
                deadline,
            )
