"""Atomic execution-journal scenarios through a per-node transaction port."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from node_protocol import Deployment
from node_protocol.control import ControlCommand
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.journal import (
    AcquireJournal,
    AdmitForward,
    ApplyOperation,
    ConfigureJournal,
    FindFailedCandidate,
    ForwardTarget,
    GetConfiguration,
    GetOperation,
    JournalConfiguration,
    JournalEvent,
    JournalOperation,
    JournalRequest,
    JournalResult,
    MatchApplied,
    PhaseOperation,
    ReadCursor,
    ReadEvents,
    ReleaseJournal,
    RenewJournal,
    ReserveOperation,
    RestoreOperation,
)
from projects.domain.execution_journal import (
    JournalConflict,
    JournalRejected,
    WriterLease,
    acquire_writer,
    require_configuration,
    require_operation_replay,
)


@dataclass(frozen=True)
class AppliedExecution:
    spec: Deployment
    container: str


@dataclass(frozen=True)
class JournalAuthority:
    node_uuid: UUID
    pending: bool
    enabled: bool
    valid_until: int | None = None


class JournalSession(Protocol):
    async def lease(self) -> WriterLease | None: ...
    async def save_lease(self, lease: WriterLease) -> None: ...
    async def configuration(self) -> JournalConfiguration | None: ...
    async def save_configuration(self, configuration: JournalConfiguration) -> None: ...
    async def operation(self, operation: UUID) -> JournalOperation | None: ...
    async def latest(self, placement: UUID) -> JournalOperation | None: ...
    async def save_operation(self, operation: JournalOperation) -> None: ...
    async def applied(self, placement: UUID) -> AppliedExecution | None: ...
    async def save_applied(self, placement: UUID, applied: AppliedExecution) -> None: ...
    async def require_intent(self, command: ControlCommand) -> None: ...
    async def event(self, fact: "ConfigurationFact | OperationFact", now: int) -> None: ...
    async def events_after(self, cursor: int) -> tuple[JournalEvent, ...]: ...
    async def event_cursor(self) -> int: ...
    async def admit_nonce(self, request: UUID, expires_at: int, now: int) -> None: ...
    async def failed_candidate(self, value: FindFailedCandidate) -> JournalOperation | None: ...


class ExecuteJournal:
    def __init__(self, session: JournalSession, authority: JournalAuthority) -> None:
        self._store = session
        self._authority = authority

    async def execute(self, request: JournalRequest, *, now: int) -> JournalResult:
        require_journal_access(self._authority, request)
        previous = await self._store.lease()
        if isinstance(request.payload, AcquireJournal):
            lease = acquire_writer(
                previous, request.session_uuid, now=now, seconds=request.payload.lease_seconds
            )
            await self._store.save_lease(lease)
            return JournalResult(lease_epoch=lease.epoch, lease_expires_at=lease.expires_at)
        if previous is None:
            raise JournalConflict("Execution writer lease not acquired")
        previous.require_writer(request.session_uuid, request.lease_epoch, now)
        if isinstance(request.payload, (RenewJournal, ReleaseJournal)):
            return await self._lease(request, previous, now)
        if isinstance(
            request.payload, (GetConfiguration, ConfigureJournal, ReadCursor, ReadEvents)
        ):
            return await self._configuration(request, now)
        if isinstance(request.payload, (ForwardTarget, AdmitForward)):
            return await self._forward(request.payload, now)
        return await self._operations(request, now)

    async def _lease(
        self, request: JournalRequest, previous: WriterLease, now: int
    ) -> JournalResult:
        payload = request.payload
        if isinstance(payload, RenewJournal):
            lease = replace(previous, expires_at=now + payload.lease_seconds)
        else:
            lease = replace(previous, expires_at=now)
        await self._store.save_lease(lease)
        return JournalResult(lease_epoch=lease.epoch, lease_expires_at=max(1, lease.expires_at))

    async def _configuration(self, request: JournalRequest, now: int) -> JournalResult:
        payload = request.payload
        if isinstance(payload, ReadCursor):
            return JournalResult(cursor=await self._store.event_cursor())
        if isinstance(payload, ReadEvents):
            return JournalResult(events=await self._store.events_after(payload.cursor))
        previous = await self._store.configuration()
        if isinstance(payload, GetConfiguration):
            return JournalResult(configuration=previous)
        if not isinstance(payload, ConfigureJournal) or payload.core_command.node_record is None:
            raise JournalRejected("Exact journal configuration required")
        command = payload.core_command
        record = command.node_record
        if record is None:
            raise JournalRejected("Exact journal configuration required")
        changed = require_configuration(
            command.sequence,
            previous.sequence if previous else None,
            previous is not None and previous.record == record,
        )
        configuration = JournalConfiguration(sequence=command.sequence, record=record)
        await self._store.save_configuration(configuration)
        if changed:
            await self._store.event(
                ConfigurationFact(str(record.id), record.enabled, command.sequence), now
            )
        return JournalResult(configuration=configuration)

    async def _operations(self, request: JournalRequest, now: int) -> JournalResult:
        payload = request.payload
        if isinstance(payload, GetOperation):
            return JournalResult(operation=await self._store.operation(payload.operation_uuid))
        if isinstance(payload, ReserveOperation):
            return JournalResult(operation=await self._reserve(payload.core_command, now))
        if isinstance(payload, PhaseOperation):
            await self._phase(payload, now)
            return JournalResult()
        if isinstance(payload, (ApplyOperation, RestoreOperation)):
            await self._projection(payload, now)
            return JournalResult()
        if isinstance(payload, MatchApplied):
            applied = await self._store.applied(payload.desired.id)
            matched = bool(
                applied
                and applied.container == payload.container
                and applied.spec.fingerprint == payload.desired.fingerprint
            )
            return JournalResult(matched=matched)
        if isinstance(payload, FindFailedCandidate):
            candidate = await self._store.failed_candidate(payload)
            return JournalResult(matched=candidate_matches(candidate, payload.desired))
        raise JournalRejected("Unsupported journal action")

    async def _reserve(self, command: ControlCommand, now: int) -> JournalOperation:
        desired = command.deployment
        if desired is None or not self._authority.enabled or not desired.enabled:
            raise JournalRejected("Current enabled node deployment required")
        await self._store.require_intent(command)
        existing = await self._store.operation(command.operation_uuid)
        if existing is not None:
            require_operation_replay(
                command.sequence, existing.sequence, desired == existing.desired
            )
            return existing
        latest = await self._store.latest(desired.id)
        if latest is not None and (
            command.sequence <= latest.sequence or latest.phase not in {"succeeded", "failed"}
        ):
            raise JournalConflict("Stale or active placement command")
        applied = await self._store.applied(desired.id)
        operation = JournalOperation(
            id=str(command.operation_uuid),
            placement=str(desired.id),
            sequence=command.sequence,
            desired=desired,
            fingerprint=desired.fingerprint,
            phase="queued",
            previous=applied.spec if applied else None,
        )
        await self._store.save_operation(operation)
        await self._operation_event(operation, now)
        return operation

    async def _phase(self, payload: PhaseOperation, now: int) -> None:
        previous = await self._required_operation(payload.operation_uuid)
        diagnostic = previous.diagnostic or payload.diagnostic
        operation = previous.model_copy(
            update={
                "phase": payload.phase,
                "error": payload.error,
                "container": payload.container
                if payload.container is not None
                else previous.container,
                "diagnostic": diagnostic,
            }
        )
        await self._store.save_operation(operation)
        if (previous.phase, previous.error, previous.diagnostic) != (
            operation.phase,
            operation.error,
            operation.diagnostic,
        ):
            await self._operation_event(operation, now)

    async def _projection(self, payload: ApplyOperation | RestoreOperation, now: int) -> None:
        operation = await self._required_operation(payload.operation_uuid)
        if isinstance(payload, ApplyOperation):
            if payload.desired != operation.desired:
                raise JournalConflict("Applied deployment differs from reserved intent")
            await self._store.save_applied(
                payload.desired.id, AppliedExecution(operation.desired, payload.container)
            )
            await self._phase(
                PhaseOperation(
                    operation_uuid=payload.operation_uuid,
                    phase="succeeded",
                    container=payload.container,
                ),
                now,
            )
            return
        if payload.previous != operation.previous:
            raise JournalConflict("Restoration differs from retained deployment")
        await self._store.save_applied(
            payload.previous.id,
            AppliedExecution(payload.previous, payload.container),
        )

    async def _required_operation(self, operation_uuid: UUID) -> JournalOperation:
        operation = await self._store.operation(operation_uuid)
        if operation is None:
            raise JournalConflict("Operation not found")
        return operation

    async def _operation_event(self, operation: JournalOperation, now: int) -> None:
        await self._store.event(
            OperationFact(
                operation.id,
                operation.sequence,
                operation.phase,
                operation.error,
                operation.diagnostic,
            ),
            now,
        )

    async def _forward(self, payload: ForwardTarget | AdmitForward, now: int) -> JournalResult:
        proof = payload.proof
        if not self._authority.enabled or proof.expires_at <= now:
            raise JournalRejected("Current forwarding authority required")
        applied = await self._store.applied(proof.placement_uuid)
        latest = await self._store.latest(proof.placement_uuid)
        if applied is None or (
            latest
            and (latest.phase not in {"succeeded", "failed"} or latest.error == "ROLLBACK_FAILED")
        ):
            raise JournalConflict("Placement is unavailable or updating")
        require_forward_target(applied.spec, payload)
        if isinstance(payload, AdmitForward):
            await self._store.admit_nonce(proof.request_uuid, proof.expires_at, now)
        return JournalResult(container=applied.container)


def candidate_matches(candidate: JournalOperation | None, desired: Deployment) -> bool:
    if candidate is None:
        return False
    previous = candidate.desired
    return (
        previous.node_uuid == desired.node_uuid
        and previous.project_uuid == desired.project_uuid
        and previous.release.module == desired.release.module
        and previous.workspace == desired.workspace
    )


def require_journal_access(authority: JournalAuthority, request: JournalRequest) -> None:
    if authority.pending and request.action not in {
        "acquire",
        "renew",
        "release",
        "configuration",
        "event_cursor",
    }:
        raise JournalRejected("Paired node identity required")
    if not authority.enabled and request.action in {"reserve", "forward_target", "admit_forward"}:
        raise JournalRejected("Current enabled Node required")


def require_forward_target(spec: Deployment, payload: ForwardTarget | AdmitForward) -> None:
    proof = payload.proof
    if (
        not spec.enabled
        or spec.node_uuid != proof.node_uuid
        or spec.project_uuid != proof.project_uuid
        or spec.fingerprint != proof.fingerprint
        or spec.release.module != proof.module
        or spec.release.port != proof.port
    ):
        raise JournalConflict("Forwarding proof does not match the applied placement")


@dataclass(frozen=True)
class ConfigurationFact:
    node_uuid: str
    enabled: bool
    sequence: int


@dataclass(frozen=True)
class OperationFact:
    operation_uuid: str
    sequence: int
    phase: str
    error: str | None
    diagnostic: FailureDiagnostic | None
