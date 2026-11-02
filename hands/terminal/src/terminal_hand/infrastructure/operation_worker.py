"""Existing child lifecycle and bounded IPC adapted to the execution port."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from hand_runtime.process_lease_domain import LeaseIdentity
from terminal_hand.infrastructure.worker_messages import TerminalReply


class SupervisedProcess(Protocol):
    @property
    def child(self) -> asyncio.subprocess.Process | None: ...
    @property
    def lease(self) -> LeaseIdentity | None: ...
    @property
    def lease_until(self) -> float: ...


class SupervisorOperationWorker:
    def __init__(
        self,
        supervisor: SupervisedProcess,
        start: Callable[[], Awaitable[None]],
        stop: Callable[[], Awaitable[None]],
        operation: UUID,
        request: bytes,
        validate: Callable[[TerminalReply], None] | None = None,
    ) -> None:
        self._supervisor, self._start, self._stop = supervisor, start, stop
        self._operation, self._request = operation, request
        self._validate = validate

    def authority_current(self) -> bool:
        return (
            self._supervisor.lease is not None and time.monotonic() < self._supervisor.lease_until
        )

    async def prepare(self) -> None:
        child = self._supervisor.child
        if child is None or child.returncode is not None:
            await self._start()

    async def stop(self) -> None:
        await self._stop()

    async def dispatch(self) -> TerminalReply:
        child = self._supervisor.child
        if child is None or child.stdin is None or child.stdout is None:
            raise ValueError("Terminal worker did not confirm the operation")
        child.stdin.write(self._request + b"\n")
        await child.stdin.drain()
        raw = await child.stdout.readline()
        if not raw or len(raw) > 1_000_000:
            raise ValueError("Terminal worker did not confirm the operation")
        reply = TerminalReply.model_validate_json(raw)
        if reply.id != self._operation:
            raise ValueError("Terminal reply operation mismatch")
        if self._validate is not None:
            self._validate(reply)
        return reply
