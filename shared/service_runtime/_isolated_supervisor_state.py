"""Read existing isolated process state and poll its unchanged lease controller."""

import asyncio
from abc import ABC, abstractmethod
from asyncio.subprocess import Process
from typing import Protocol


class _ExpiringProcessLease(Protocol):
    async def pause_expired(self) -> bool: ...


class _IsolatedSupervisorState[LeaseT: _ExpiringProcessLease](ABC):
    child: Process | None
    prepared: bool
    lease: LeaseT
    lock: asyncio.Lock
    watchdog_task: asyncio.Task[None] | None

    @abstractmethod
    async def _prepare_child(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    async def warmup(self) -> None:
        async with self.lock:
            if self.ready():
                return
            await self.stop()
            try:
                await self._prepare_child()
                self.prepared = True
                if self.watchdog_task is None:
                    self.watchdog_task = asyncio.create_task(self.watchdog())
            except BaseException:
                await self.stop()
                raise

    def ready(self) -> bool:
        return bool(self.prepared and self.child and self.child.returncode is None)

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            await self.lease.pause_expired()
