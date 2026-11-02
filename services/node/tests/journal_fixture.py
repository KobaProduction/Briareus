"""Async journal port double for native-effect tests, not a persistence backend.

PostgreSQL atomicity, leases and replay durability are tested by Resources.
This double supplies controlled observations to Node application/transport tests.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from node_agent.domain.placement import OperationConflict

from node_protocol import Deployment, NodeRecord
from node_protocol.control import ControlCommand
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.forward import ForwardProof
from node_protocol.journal import (
    JournalConfiguration,
    JournalConfigurationEvent,
    JournalEvent,
    JournalOperation,
    JournalOperationEvent,
)


@dataclass
class JournalState:
    operations: dict[UUID, JournalOperation] = field(default_factory=dict)
    applied: dict[UUID, tuple[Deployment, str]] = field(default_factory=dict)
    configuration: JournalConfiguration | None = None
    events: list[JournalEvent] = field(default_factory=list)
    admitted: set[UUID] = field(default_factory=set)


class JournalFixture:
    states: dict[Path, JournalState] = {}

    def __init__(self, namespace: Path) -> None:
        self.state = self.states.setdefault(namespace, JournalState())
        self.lost = asyncio.Event()
        self.listeners: set[asyncio.Event] = set()

    @contextmanager
    def authority(self, command: ControlCommand, signature: str) -> Iterator[None]:
        del command, signature
        yield

    async def close(self) -> None:
        pass

    async def configuration(self) -> JournalConfiguration | None:
        return self.state.configuration

    async def configure(self, sequence: int, record: NodeRecord) -> None:
        previous = self.state.configuration
        if previous is not None and (
            sequence < previous.sequence
            or (sequence == previous.sequence and record != previous.record)
        ):
            raise OperationConflict("Fixture configuration conflict")
        self.state.configuration = JournalConfiguration(sequence=sequence, record=record)
        if previous != self.state.configuration:
            self._event(
                JournalConfigurationEvent(
                    node_uuid=record.id, sequence=sequence, enabled=record.enabled
                )
            )

    async def get(self, operation: UUID) -> JournalOperation | None:
        return self.state.operations.get(operation)

    async def reserve(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> JournalOperation:
        current = self.state.operations.get(operation)
        if current is not None:
            return current
        previous = self.state.applied.get(desired.id)
        current = JournalOperation(
            id=str(operation),
            placement=str(desired.id),
            sequence=sequence,
            desired=desired,
            fingerprint=desired.fingerprint,
            phase="queued",
            previous=previous[0] if previous else None,
        )
        self.state.operations[operation] = current
        self._operation_event(operation, current)
        return current

    async def phase(
        self,
        operation: UUID,
        phase: str,
        *,
        container: str | None = None,
        error: str | None = None,
        diagnostic: FailureDiagnostic | None = None,
    ) -> None:
        previous = self.state.operations[operation]
        current = JournalOperation.model_validate(
            {
                **previous.model_dump(),
                "phase": phase,
                "container": container or previous.container,
                "error": error,
                "diagnostic": previous.diagnostic or diagnostic,
            }
        )
        self.state.operations[operation] = current
        if current != previous:
            self._operation_event(operation, current)

    def seed_applied(self, spec: Deployment, container: str) -> None:
        self.state.applied[spec.id] = (spec, container)

    async def applied(self, operation: UUID, spec: Deployment, container_id: str) -> None:
        self.seed_applied(spec, container_id)
        await self.phase(operation, "succeeded", container=container_id)

    async def restore(self, operation: UUID, spec: Deployment, container: str) -> None:
        del operation
        self.seed_applied(spec, container)

    async def matches_applied(self, desired: Deployment, container: str) -> bool:
        current = self.state.applied.get(desired.id)
        return (
            current is not None
            and current[1] == container
            and current[0].fingerprint == desired.fingerprint
        )

    async def failed_candidate(
        self,
        desired: Deployment,
        container: str,
        fingerprint: str,
        before_sequence: int,
    ) -> bool:
        return any(
            row.placement == str(desired.id)
            and row.container == container
            and row.fingerprint == fingerprint
            and row.sequence < before_sequence
            and row.phase == "failed"
            for row in self.state.operations.values()
        )

    async def forward_target(self, proof: ForwardProof, gateway_signature: str = "") -> str:
        del gateway_signature
        current = self.state.applied.get(proof.placement_uuid)
        if current is None or current[0].project_uuid != proof.project_uuid:
            raise OperationConflict("Fixture placement unavailable")
        operations = [
            row
            for row in self.state.operations.values()
            if row.placement == str(proof.placement_uuid)
        ]
        if operations:
            latest = max(operations, key=lambda row: row.sequence)
            if latest.phase not in {"succeeded", "failed"} or latest.error == "ROLLBACK_FAILED":
                raise OperationConflict("Fixture placement updating")
        return current[1]

    async def admit_forward(self, proof: ForwardProof, gateway_signature: str = "") -> str:
        target = await self.forward_target(proof, gateway_signature)
        if proof.request_uuid in self.state.admitted:
            raise OperationConflict("Fixture repeated request")
        self.state.admitted.add(proof.request_uuid)
        return target

    async def events_after(self, cursor: int) -> tuple[JournalEvent, ...]:
        return tuple(event for event in self.state.events if event.cursor > cursor)[:128]

    async def event_cursor(self) -> int:
        return self.state.events[-1].cursor if self.state.events else 0

    def _operation_event(self, operation: UUID, row: JournalOperation) -> None:
        self._event(
            JournalOperationEvent(
                operation_uuid=operation,
                sequence=row.sequence,
                phase=row.phase,
                error=row.error,
                diagnostic=row.diagnostic,
            )
        )

    def _event(self, payload: JournalOperationEvent | JournalConfigurationEvent) -> None:
        self.state.events.append(
            JournalEvent(
                cursor=len(self.state.events) + 1,
                topic="operation"
                if isinstance(payload, JournalOperationEvent)
                else "configuration",
                payload=payload,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        for listener in self.listeners:
            listener.set()
