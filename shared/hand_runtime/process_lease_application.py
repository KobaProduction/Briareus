"""Lease replacement and stable pause confirmation through process control ports."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Literal

from hand_runtime.process_lease_domain import (
    LeaseIdentity,
    ProcessAuthority,
    ProcessInventory,
    stopped_processes,
)


class ProcessLeaseController(ABC):
    def __init__(self, uid: int) -> None:
        self.uid = uid
        self.identity: LeaseIdentity | None = None
        self.expires_at = 0.0
        self._deadline = 0.0
        self.paused = False
        self._lock = asyncio.Lock()

    @property
    def status(self) -> Literal["unleased", "paused", "active"]:
        if self.identity is None:
            return "unleased"
        return "paused" if self.paused else "active"

    @abstractmethod
    def _processes(self) -> ProcessInventory: ...

    @abstractmethod
    def _terminate(self, processes: Iterable[int]) -> None: ...

    @abstractmethod
    def _stop(self, processes: Iterable[int]) -> None: ...

    @abstractmethod
    def _resume(self, processes: Iterable[int]) -> None: ...

    async def _kill(self) -> None:
        self.identity = None
        self.expires_at = self._deadline = 0.0
        self.paused = False
        for _ in range(40):
            processes = self._processes()
            if not processes:
                return
            self._terminate(processes)
            await asyncio.sleep(0.01)
        raise RuntimeError("Worker process termination could not be confirmed")

    async def kill(self) -> None:
        async with self._lock:
            await self._kill()

    async def grant(self, identity_tuple: LeaseIdentity, expires_at: float) -> bool:
        """Resume only the same actor/session/revision; report whether it survived."""
        ProcessAuthority(identity_tuple, expires_at).require_current(time.time())
        async with self._lock:
            preserved = self.identity == identity_tuple
            if self.identity is not None and not preserved:
                await self._kill()
            self.identity = identity_tuple
            self.expires_at = expires_at
            self._deadline = time.monotonic() + max(0, expires_at - time.time())
            if self.paused:
                self._resume(self._processes())
            self.paused = False
            return preserved

    async def _confirm_pause(self) -> None:
        stable: set[int] | None = None
        for _ in range(30):
            self._stop(self._processes())
            await asyncio.sleep(0.01)
            after = self._processes()
            stopped = stopped_processes(after.values())
            observed = set(after)
            if observed == stable and stopped:
                self.paused = True
                return
            stable = observed if stopped else None
        raise RuntimeError("Worker pause could not be confirmed")

    async def pause_expired(self) -> bool:
        """Stop the entire UID and confirm stable stopped state, or kill it."""
        async with self._lock:
            if self.identity is None or self.paused or time.monotonic() < self._deadline:
                return self.paused
            try:
                await self._confirm_pause()
                return True
            except BaseException:
                await self._kill()
                raise
