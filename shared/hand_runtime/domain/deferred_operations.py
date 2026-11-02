"""Process-local operation identity and terminal-state facts, without SDK dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from hand_runtime.process_lease_domain import LeaseIdentity


@dataclass(frozen=True, slots=True)
class OperationHandle:
    boot: UUID | None
    request_uuid: UUID


class OperationState(StrEnum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True)
class OperationAuthority:
    identity: LeaseIdentity
    expires_at: int
    request_uuid: UUID


@dataclass(frozen=True)
class ProviderOperationBinding:
    account_id: str | None
    provider: str | None
    context_digest: str


@dataclass
class DeferredRecord[ResultT]:
    operation_id: OperationHandle
    identity: LeaseIdentity
    tool: str
    state: OperationState = OperationState.RUNNING
    result: ResultT | None = None
    provider_binding: ProviderOperationBinding | None = None

    def complete(self, result: ResultT, *, failed: bool) -> None:
        if self.state == OperationState.RUNNING:
            self.result = result
            self.state = OperationState.FAILED if failed else OperationState.COMPLETED


@dataclass(frozen=True)
class ExecutionOutcome[ResultT]:
    result: ResultT
    failed: bool


class OperationEntry(Protocol):
    @property
    def operation_id(self) -> OperationHandle: ...

    @property
    def state(self) -> OperationState: ...


class OperationIndex[RecordT: OperationEntry]:
    def __init__(self, boot: UUID) -> None:
        self.boot = boot
        self._records: dict[OperationHandle, RecordT] = {}

    def lookup(self, operation_id: OperationHandle) -> RecordT | None:
        key = (
            OperationHandle(self.boot, operation_id.request_uuid)
            if operation_id.boot is None
            else operation_id
        )
        return self._records.get(key)

    def values(self) -> tuple[RecordT, ...]:
        return tuple(self._records.values())

    def running(self) -> bool:
        return any(record.state == OperationState.RUNNING for record in self._records.values())

    def require_new(self, request_uuid: UUID) -> OperationHandle:
        operation = OperationHandle(self.boot, request_uuid)
        if operation in self._records:
            raise ValueError("Start already received; poll its handle")
        return operation

    def allocate(self, request_uuid: UUID) -> OperationHandle:
        operation = self.require_new(request_uuid)
        while len(self._records) >= 32:
            self._records.pop(next(iter(self._records)))
        return operation

    def insert(self, record: RecordT) -> None:
        self._records[record.operation_id] = record


class DeferredBook[ResultT](OperationIndex[DeferredRecord[ResultT]]):
    """Bounded operation index specialized for results of asynchronous dispatch."""
