"""Process-local task supervision; durable operation authority remains in Resources."""

import asyncio
import logging
import traceback
from pathlib import Path
from uuid import UUID

from node_agent.controller import Controller
from node_agent.journal import Journal, JournalUnavailable, OperationConflict
from node_protocol.control import ControlCommand
from node_protocol.diagnostics import FailureDiagnostic

LOG = logging.getLogger(__name__)


class NodeExecutionTasks:
    def __init__(self, controller: Controller, journal: Journal) -> None:
        self._controller, self._journal = controller, journal
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._watcher: asyncio.Task[None] | None = None
        self._stopping = False

    def draining(self) -> bool:
        return self._stopping or self._journal.lost.is_set()

    def active(self, operation: UUID) -> bool:
        return operation in self._tasks

    def full(self) -> bool:
        return len(self._tasks) >= 16

    def schedule(self, command: ControlCommand) -> None:
        self._tasks[command.operation_uuid] = asyncio.create_task(self._execute(command))

    def watch_lease(self) -> None:
        if self._watcher is None:
            self._watcher = asyncio.create_task(self._watch_lease())

    async def _watch_lease(self) -> None:
        await self._journal.lost.wait()
        self._stopping = True
        await self._cancel_operations()

    async def _cancel_operations(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, command: ControlCommand) -> None:
        try:
            if command.deployment is None:
                raise ValueError("Admitted deployment required")
            await self._controller.apply(
                command.operation_uuid, command.sequence, command.deployment
            )
        except JournalUnavailable:
            LOG.error("Node execution journal unavailable; durable phase retained")
        except Exception as error:
            frames = traceback.extract_tb(error.__traceback__)
            LOG.error(
                "Node operation failed: %s at %s",
                type(error).__name__,
                [(Path(frame.filename).name, frame.name, frame.lineno) for frame in frames],
            )
            await self._record_failure(command.operation_uuid)
        finally:
            self._tasks.pop(command.operation_uuid, None)

    async def _record_failure(self, operation: UUID) -> None:
        try:
            current = await self._journal.get(operation)
            if current is not None and current.phase not in {"succeeded", "failed"}:
                diagnostic = FailureDiagnostic.model_validate(
                    {
                        "stage": current.phase,
                        "component": "controller",
                        "reason": "unknown",
                    }
                )
                await self._journal.phase(
                    operation, "failed", error="UPDATE_FAILED", diagnostic=diagnostic
                )
        except (JournalUnavailable, OperationConflict):
            LOG.error("Node execution receipt unavailable; durable phase retained")

    async def close(self) -> None:
        self._stopping = True
        if self._watcher is not None:
            self._watcher.cancel()
            await asyncio.gather(self._watcher, return_exceptions=True)
        await self._cancel_operations()
