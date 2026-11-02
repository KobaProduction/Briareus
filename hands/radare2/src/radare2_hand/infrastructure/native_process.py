"""Pinned native process driver with finite output and process-group cleanup."""

import asyncio
import os
import signal
import tempfile
import time
from contextlib import suppress

from radare2_hand.domain.binaries import MAX_OUTPUT, R2_VERSION


class NativeProcesses:
    def __init__(self, executable: str) -> None:
        self.executable = executable
        self.processes: set[asyncio.subprocess.Process] = set()
        self.ready = False

    async def run(self, arguments: list[str], deadline: float | None) -> bytes:
        if deadline is not None and deadline <= time.time():
            raise ValueError("Current analysis authority expired")
        temporary = tempfile.gettempdir()
        process = await asyncio.create_subprocess_exec(
            self.executable,
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": temporary,
                "TMPDIR": temporary,
                "LANG": "C.UTF-8",
                "R2_NOPLUGINS": "1",
            },
        )
        self.processes.add(process)
        try:
            timeout = max(0, deadline - time.time()) if deadline is not None else None
            async with asyncio.timeout(timeout):
                return await bounded_output(process, deadline)
        finally:
            await terminate(process)
            self.processes.discard(process)

    async def startup(self) -> None:
        version = await self.run(["-v"], time.time() + 4)
        if not version.decode().splitlines()[0].startswith("radare2 " + R2_VERSION + " "):
            raise ValueError("The approved pinned radare2 version is required")
        self.ready = True

    async def close(self) -> None:
        self.ready = False
        cohort = tuple(self.processes)
        for process in cohort:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
        await asyncio.gather(*(process.wait() for process in cohort))


async def bounded_output(process: asyncio.subprocess.Process, deadline: float | None) -> bytes:
    if process.stdout is None:
        raise ValueError("Native analysis output required")
    output = bytearray()
    while chunk := await process.stdout.read(65536):
        output.extend(chunk)
        if len(output) > MAX_OUTPUT:
            raise ValueError("Analysis output exceeds limit; narrow the request")
    await process.wait()
    if process.returncode != 0 or (deadline is not None and deadline <= time.time()):
        raise ValueError("Native analysis did not complete under current authority")
    return bytes(output)


async def terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
