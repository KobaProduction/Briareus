"""Preparation and scheduling for owner-specific private process supervisors."""

from __future__ import annotations

import asyncio

from service_runtime._isolated_supervisor_state import _IsolatedSupervisorState

from .process_lease import ProcessLease


class _SupervisorLifecycle(_IsolatedSupervisorState[ProcessLease]):
    warming: asyncio.Task[None] | None

    def ready(self) -> bool:
        return bool(self.prepared and self.child is not None and self.child.returncode is None)

    def _schedule_warmup(self) -> None:
        if self.warming is not None and not self.warming.done():
            return
        self.warming = asyncio.create_task(self.warmup())
        self.warming.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            try:
                await self.lease.pause_expired()
            except Exception:
                async with self.lock:
                    await self.stop()
                    self._schedule_warmup()
