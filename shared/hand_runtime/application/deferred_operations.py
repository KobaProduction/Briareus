"""Bounded asynchronous execution; process leases remain the execution authority."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from hand_runtime.domain.deferred_operations import (
    DeferredBook,
    DeferredRecord,
    ExecutionOutcome,
    OperationAuthority,
    OperationHandle,
    OperationState,
)
from hand_runtime.process_lease_domain import LeaseIdentity


class OperationLease(Protocol):
    @property
    def identity(self) -> LeaseIdentity | None: ...

    async def grant(self, identity: LeaseIdentity, expires_at: float) -> bool: ...


class DeferredOperations[ResultT]:
    def __init__(
        self,
        *,
        boot: UUID,
        lock: asyncio.Lock,
        lease: OperationLease,
        ready: Callable[[], bool],
        stop: Callable[[], Awaitable[None]],
        recover: Callable[[], None],
        clock: Callable[[], float],
        timeout: Callable[[], float | None],
    ) -> None:
        self.book = DeferredBook[ResultT](boot)
        self._lock, self._lease, self._ready = lock, lease, ready
        self._stop, self._recover = stop, recover
        self._clock, self._timeout = clock, timeout
        self._tasks: dict[OperationHandle, asyncio.Task[None]] = {}

    def interrupt(self) -> None:
        for record in self.book.values():
            if record.state == OperationState.RUNNING:
                record.state = OperationState.INTERRUPTED
                task = self._tasks.get(record.operation_id)
                if task is not None and task is not asyncio.current_task():
                    task.cancel()

    def _prune_tasks(self) -> None:
        for operation in tuple(self._tasks):
            if self.book.lookup(operation) is None:
                self._tasks.pop(operation)

    async def start(
        self,
        tool: str,
        authority: OperationAuthority,
        dispatch: Callable[[], Awaitable[ExecutionOutcome[ResultT]]],
    ) -> DeferredRecord[ResultT]:
        if not self._ready() or authority.expires_at <= self._clock() or self.book.running():
            raise ValueError("Bounded original tool and prepared runtime required")
        operation = self.book.allocate(authority.request_uuid)
        self._prune_tasks()
        await self._lease.grant(authority.identity, authority.expires_at)
        record = DeferredRecord[ResultT](operation, authority.identity, tool)
        self.book.insert(record)
        self._tasks[operation] = asyncio.create_task(self._run(record, dispatch))
        return record

    async def control(
        self,
        operation: OperationHandle,
        *,
        polling: bool,
        tool: str | None,
        authority: OperationAuthority,
    ) -> DeferredRecord[ResultT]:
        record = self.book.lookup(operation)
        if (
            record is None
            or record.identity != authority.identity
            or authority.expires_at <= self._clock()
            or (polling and tool != record.tool)
        ):
            raise ValueError("Operation unavailable for this identity and tool")
        if record.state == OperationState.RUNNING:
            await self._control_running(record, authority, polling=polling)
        return record

    async def _control_running(
        self,
        record: DeferredRecord[ResultT],
        authority: OperationAuthority,
        *,
        polling: bool,
    ) -> None:
        if not polling:
            await self._stop()
            record.state = OperationState.CANCELLED
            self._recover()
            return
        if not self._ready() or self._lease.identity != authority.identity:
            raise ValueError("Original prepared execution runtime required")
        await self._lease.grant(authority.identity, authority.expires_at)

    async def _run(
        self,
        record: DeferredRecord[ResultT],
        dispatch: Callable[[], Awaitable[ExecutionOutcome[ResultT]]],
    ) -> None:
        try:
            async with asyncio.timeout(self._timeout()):
                outcome = await dispatch()
            async with self._lock:
                record.complete(outcome.result, failed=outcome.failed)
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._lock:
                await self._stop()
                record.state = OperationState.FAILED
                self._recover()
