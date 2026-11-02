"""Translate existing journal/native failures into typed application ports."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol
from uuid import UUID

from node_agent.application.placement import OperationSnapshot, RuntimeFailure
from node_agent.docker_engine import EngineFailure
from node_agent.domain.placement import OperationConflict
from node_agent.planner import Instance
from node_protocol import Deployment
from node_protocol.diagnostics import FailureDiagnostic

from .journal_records import OperationRecord


class _ControllerBinding[ControllerT]:
    def __init__(self, controller: ControllerT) -> None:
        self._controller = controller


class NativeJournal(Protocol):
    async def reserve(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> OperationRecord: ...

    async def get(self, operation: UUID) -> OperationRecord | None: ...

    async def phase(
        self,
        operation: UUID,
        phase: str,
        *,
        container: str | None = None,
        error: str | None = None,
        diagnostic: FailureDiagnostic | None = None,
    ) -> None: ...

    async def applied(self, operation: UUID, spec: Deployment, container_id: str) -> None: ...

    async def restore(self, operation: UUID, spec: Deployment, container: str) -> None: ...

    async def matches_applied(self, desired: Deployment, container: str) -> bool: ...

    async def failed_candidate(
        self, desired: Deployment, container: str, fingerprint: str, sequence: int
    ) -> bool: ...


def operation_snapshot(row: OperationRecord | None) -> OperationSnapshot:
    if row is None:
        raise OperationConflict("Operation not found")
    return OperationSnapshot(
        row.sequence,
        row.phase,
        row.previous,
        row.container,
        row.diagnostic,
    )


class _JournalBinding:
    def __init__(self, journal: NativeJournal) -> None:
        self._journal = journal


class JournalOperationStore(_JournalBinding):
    async def reserve(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> OperationSnapshot:
        return operation_snapshot(await self._journal.reserve(operation, sequence, desired))

    async def current(self, operation: UUID) -> OperationSnapshot:
        return operation_snapshot(await self._journal.get(operation))

    async def phase(
        self,
        operation: UUID,
        phase: str,
        *,
        container: str | None = None,
        error: str | None = None,
        diagnostic: FailureDiagnostic | None = None,
    ) -> None:
        await self._journal.phase(
            operation, phase, container=container, error=error, diagnostic=diagnostic
        )

    async def applied(self, operation: UUID, desired: Deployment, container: str) -> None:
        await self._journal.applied(operation, desired, container)

    async def restore(self, operation: UUID, previous: Deployment, container: str) -> None:
        await self._journal.restore(operation, previous, container)

    async def matches_applied(self, desired: Deployment, container: str) -> bool:
        return await self._journal.matches_applied(desired, container) is True

    async def failed_candidate(
        self, desired: Deployment, container: str, fingerprint: str, sequence: int
    ) -> bool:
        return (
            await self._journal.failed_candidate(desired, container, fingerprint, sequence) is True
        )


class NativePlacementEngine(Protocol):
    async def verify_rootless(self) -> None: ...

    async def resume_applied(self, desired: Deployment) -> str: ...

    async def pull(self, desired: Deployment) -> None: ...

    async def remove_target(self, desired: Deployment, container: str) -> None: ...

    async def stage(self, desired: Deployment) -> str: ...


class ControllerExecution(Protocol):
    @property
    def engine(self) -> NativePlacementEngine: ...

    async def observed(self) -> list[Instance]: ...

    async def wait_ready(self, container: str) -> None: ...

    async def failure_diagnostic(
        self, receipt: OperationSnapshot, desired: Deployment, *, deadline_expired: bool = False
    ) -> FailureDiagnostic: ...


@contextmanager
def translate_failure() -> Iterator[None]:
    try:
        yield
    except EngineFailure as failure:
        raw: object = failure.diagnostic
        reason: object = failure.reason
        diagnostic = FailureDiagnostic.model_validate(raw) if raw is not None else None
        raise RuntimeFailure(diagnostic, reason if isinstance(reason, str) else None) from failure


class _ControllerObservations[ControllerT: ControllerExecution](_ControllerBinding[ControllerT]):
    async def verify_rootless(self) -> None:
        with translate_failure():
            await self._controller.engine.verify_rootless()

    async def observed(self) -> list[Instance]:
        with translate_failure():
            return await self._controller.observed()


class ControllerPlacementRuntime(_ControllerObservations[ControllerExecution]):
    async def resume_applied(self, desired: Deployment) -> str:
        with translate_failure():
            return await self._controller.engine.resume_applied(desired)

    async def wait_ready(self, container: str) -> None:
        with translate_failure():
            await self._controller.wait_ready(container)

    async def pull(self, desired: Deployment) -> None:
        with translate_failure():
            await self._controller.engine.pull(desired)

    async def remove_target(self, desired: Deployment, container: str) -> None:
        with translate_failure():
            await self._controller.engine.remove_target(desired, container)

    async def stage(self, desired: Deployment) -> str:
        with translate_failure():
            return await self._controller.engine.stage(desired)

    async def diagnose(
        self, receipt: OperationSnapshot, desired: Deployment, *, deadline_expired: bool
    ) -> FailureDiagnostic:
        return await self._controller.failure_diagnostic(
            receipt,
            desired,
            deadline_expired=deadline_expired,
        )
