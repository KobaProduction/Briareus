"""Fenced writer session over the authoritative Resources PostgreSQL journal."""

import asyncio
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID, uuid4

from node_agent.domain.placement import OperationConflict
from node_protocol import Deployment, NodeRecord
from node_protocol.control import ControlCommand
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.forward import TransportProof
from node_protocol.journal import (
    AcquireJournal,
    AdmitForward,
    ApplyOperation,
    ConfigureJournal,
    FindFailedCandidate,
    ForwardTarget,
    GetConfiguration,
    GetOperation,
    JournalAction,
    JournalConfiguration,
    JournalEvent,
    JournalOperation,
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

from .controller_lock import WriterLock
from .journal_client import JournalUnavailable, SignedJournalClient


@dataclass(frozen=True, slots=True)
class CoreAuthority:
    command: ControlCommand
    signature: str


_authority: ContextVar[CoreAuthority | None] = ContextVar("journal_core_authority", default=None)


class Journal:
    def __init__(self, client: SignedJournalClient, writer_lock: WriterLock) -> None:
        self._client, self._writer_lock = client, writer_lock
        self._session = uuid4()
        self._epoch: int | None = None
        self._expires_at = 0
        self._starting = asyncio.Lock()
        self._heartbeat: asyncio.Task[None] | None = None
        self._closed = False
        self.lost = asyncio.Event()
        self.listeners: set[asyncio.Event] = set()

    @contextmanager
    def authority(self, command: ControlCommand, signature: str) -> Iterator[None]:
        token = _authority.set(CoreAuthority(command, signature))
        try:
            yield
        finally:
            _authority.reset(token)

    async def start(self) -> None:
        async with self._starting:
            if self._closed or self.lost.is_set():
                raise JournalUnavailable("Journal writer session is unavailable")
            self._writer_lock.acquire()
            if self._epoch is not None:
                if self._expires_at <= time.time():
                    self.lost.set()
                    raise JournalUnavailable("Journal writer lease expired")
                return
            result = await self._client.exchange(AcquireJournal(), self._session, None)
            self._accept_lease(result)
            self._heartbeat = asyncio.create_task(self._renew())

    def _accept_lease(self, result: JournalResult) -> None:
        if result.lease_epoch is None or result.lease_expires_at is None:
            raise JournalUnavailable("Authoritative writer lease required")
        if result.lease_expires_at <= time.time():
            raise JournalUnavailable("Current writer lease required")
        if self._epoch is not None and self._epoch != result.lease_epoch:
            raise JournalUnavailable("Writer lease epoch changed")
        self._epoch, self._expires_at = result.lease_epoch, result.lease_expires_at

    async def _renew(self) -> None:
        try:
            while True:
                await asyncio.sleep(10)
                result = await self._client.exchange(RenewJournal(), self._session, self._epoch)
                self._accept_lease(result)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logging.getLogger(__name__).error(
                "Node journal writer lease lost exception=%s cause=%s",
                type(error).__name__,
                type(error.__cause__).__name__,
            )
            self.lost.set()
            self._notify()

    async def close(self) -> None:
        self._closed = True
        if self._heartbeat is not None:
            self._heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat
        try:
            if self._epoch is not None and not self.lost.is_set():
                with suppress(JournalUnavailable, OperationConflict):
                    await self._client.exchange(ReleaseJournal(), self._session, self._epoch)
        finally:
            try:
                await self._client.close()
            finally:
                self._writer_lock.release()

    async def _call(self, payload: JournalAction, *, changed: bool = False) -> JournalResult:
        await self.start()
        try:
            result = await self._client.exchange(payload, self._session, self._epoch)
        except JournalUnavailable:
            self.lost.set()
            self._notify()
            raise
        if changed:
            self._notify()
        return result

    def _notify(self) -> None:
        for listener in tuple(self.listeners):
            listener.set()

    @staticmethod
    def _core(action: str) -> CoreAuthority:
        authority = _authority.get()
        if authority is None or authority.command.action != action or not authority.signature:
            raise OperationConflict("Authentic signed Core command required")
        return authority

    async def configuration(self) -> JournalConfiguration | None:
        return (await self._call(GetConfiguration())).configuration

    async def configure(self, sequence: int, record: NodeRecord) -> None:
        authority = self._core("configure")
        if authority.command.sequence != sequence or authority.command.node_record != record:
            raise OperationConflict("Configuration differs from signed Core authority")
        await self._call(
            ConfigureJournal(
                core_command=authority.command,
                core_signature=authority.signature,
            ),
            changed=True,
        )

    async def get(self, operation: UUID) -> JournalOperation | None:
        return (await self._call(GetOperation(operation_uuid=operation))).operation

    async def reserve(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> JournalOperation:
        authority = self._core("apply")
        if (
            authority.command.operation_uuid != operation
            or authority.command.sequence != sequence
            or authority.command.deployment != desired
        ):
            raise OperationConflict("Reservation differs from signed Core authority")
        existing = await self.get(operation)
        if existing is not None:
            if existing.sequence != sequence or existing.desired != desired:
                raise OperationConflict("Operation identity reused with different command")
            # A queued operation already accepted under fresh Core authority
            # remains durable while another placement holds the capacity lock.
            # Reading it never resubmits an expired Core delegation.
            return existing
        result = await self._call(
            ReserveOperation(
                core_command=authority.command,
                core_signature=authority.signature,
            ),
            changed=True,
        )
        if result.operation is None:
            raise JournalUnavailable("Authoritative operation receipt required")
        return result.operation

    async def phase(
        self,
        operation: UUID,
        phase: str,
        *,
        container: str | None = None,
        error: str | None = None,
        diagnostic: FailureDiagnostic | None = None,
    ) -> None:
        payload = PhaseOperation.model_validate(
            {
                "operation_uuid": operation,
                "phase": phase,
                "container": container,
                "error": error,
                "diagnostic": diagnostic,
            }
        )
        await self._call(payload, changed=True)

    async def applied(self, operation: UUID, spec: Deployment, container_id: str) -> None:
        await self._call(
            ApplyOperation(
                operation_uuid=operation,
                desired=spec,
                container=container_id,
            ),
            changed=True,
        )

    async def restore(self, operation: UUID, spec: Deployment, container: str) -> None:
        await self._call(
            RestoreOperation(
                operation_uuid=operation,
                previous=spec,
                container=container,
            ),
            changed=True,
        )

    async def matches_applied(self, desired: Deployment, container: str) -> bool:
        result = await self._call(MatchApplied(desired=desired, container=container))
        if result.matched is None:
            raise JournalUnavailable("Authoritative applied match required")
        return result.matched

    async def failed_candidate(
        self,
        desired: Deployment,
        container: str,
        fingerprint: str,
        before_sequence: int,
    ) -> bool:
        result = await self._call(
            FindFailedCandidate(
                desired=desired,
                container=container,
                fingerprint=fingerprint,
                before_sequence=before_sequence,
            )
        )
        if result.matched is None:
            raise JournalUnavailable("Authoritative candidate match required")
        return result.matched

    async def forward_target(self, proof: TransportProof, gateway_signature: str) -> str:
        result = await self._call(ForwardTarget(proof=proof, gateway_signature=gateway_signature))
        return self._container(result)

    async def admit_forward(self, proof: TransportProof, gateway_signature: str) -> str:
        result = await self._call(AdmitForward(proof=proof, gateway_signature=gateway_signature))
        return self._container(result)

    @staticmethod
    def _container(result: JournalResult) -> str:
        if result.container is None:
            raise JournalUnavailable("Authoritative forwarding target required")
        return result.container

    async def events_after(self, cursor: int) -> tuple[JournalEvent, ...]:
        return (await self._call(ReadEvents(cursor=cursor))).events

    async def event_cursor(self) -> int:
        result = await self._call(ReadCursor())
        if result.cursor is None:
            raise JournalUnavailable("Authoritative event cursor required")
        return result.cursor
