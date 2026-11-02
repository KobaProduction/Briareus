"""Authenticate one Node and atomically persist its execution facts in Resources PG."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from common.platform_errors import Conflict, PersistenceTimeout
from node_protocol import Deployment, NodeRecord
from node_protocol.control import ControlCommand
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.journal import (
    AdmitForward,
    ConfigureJournal,
    FindFailedCandidate,
    ForwardTarget,
    JournalConfiguration,
    JournalEvent,
    JournalOperation,
    JournalRequest,
    JournalResult,
    ReserveOperation,
    SignedJournalRequest,
    verify_request,
)
from projects._journal_persistence import (
    NodeJournalAdmissionRow,
    NodeJournalAppliedRow,
    NodeJournalConfigurationRow,
    NodeJournalEventRow,
    NodeJournalLeaseRow,
    NodeJournalOperationRow,
    NodeJournalRequestRow,
    NodePairIntentRow,
)
from projects._node_persistence import NodeModuleRow, NodeOperationRow, NodeRow
from projects.application.execution_journal import (
    AppliedExecution,
    ConfigurationFact,
    ExecuteJournal,
    JournalAuthority,
    OperationFact,
    require_journal_access,
)
from projects.domain.execution_journal import (
    JournalConflict as JournalConflict,
)
from projects.domain.execution_journal import (
    JournalRejected as JournalRejected,
)
from projects.domain.execution_journal import (
    JournalUnavailable as JournalUnavailable,
)
from projects.domain.execution_journal import (
    WriterLease,
    require_replay_window,
)


class SqlNodeJournal:
    def __init__(
        self,
        database: PlatformDatabase,
        core_key: Ed25519PublicKey,
        gateway_key: Ed25519PublicKey | None,
    ) -> None:
        self._database, self._core, self._gateway = database, core_key, gateway_key

    async def execute(self, envelope: SignedJournalRequest, *, now: int) -> JournalResult:
        try:
            async with self._database.transaction() as tx:
                node = await tx.scalar(
                    select(NodeRow)
                    .where(NodeRow.id == envelope.request.node_uuid)
                    .with_for_update()
                )
                if node is None or node.deleted_at is not None:
                    raise JournalRejected("Enrolled node required")
                authority = await authenticate_node(tx, node, envelope, now)
                require_journal_access(authority, envelope.request)
                verify_delegated_authority(envelope.request, self._core, self._gateway, now)
                require_configuration_owner(envelope.request, node)
                session = SqlJournalSession(tx, node.id)
                digest = hashlib.sha256(envelope.request.signing_bytes()).hexdigest()
                replay = await session.request_replay(envelope.request, digest, now)
                result = (
                    replay
                    if replay is not None
                    else await ExecuteJournal(session, authority).execute(envelope.request, now=now)
                )
                finished = int(time.time())
                if (
                    min(envelope.request.expires_at, delegated_deadline(envelope.request))
                    <= finished
                ):
                    raise JournalRejected("Journal request expired before commit")
                if authority.valid_until is not None and authority.valid_until <= finished:
                    raise JournalRejected("Operator-pinned enrollment intent expired")
                await require_commit_writer(session, envelope.request, result, finished)
                if replay is None:
                    await session.complete_request(envelope.request, digest, result)
                return result
        except IntegrityError:
            raise JournalConflict("Concurrent execution journal operation") from None
        except Conflict:
            raise JournalConflict("Execution journal concurrency conflict") from None
        except (DBAPIError, PersistenceTimeout):
            raise JournalUnavailable("Execution journal persistence unavailable") from None


def public_key(value: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(value.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise JournalRejected("Pinned Node Ed25519 identity required")
    return key


async def authenticate_node(
    tx: AsyncSession, node: NodeRow, envelope: SignedJournalRequest, now: int
) -> JournalAuthority:
    if node.public_key:
        try:
            verify_request(envelope, public_key(node.public_key), node_uuid=node.id, now=now)
        except ValueError:
            raise JournalRejected("Node journal signature rejected") from None
        return JournalAuthority(node.id, False, node.enabled)
    intents = await tx.scalars(
        select(NodePairIntentRow)
        .where(
            NodePairIntentRow.node_uuid == node.id,
            NodePairIntentRow.expected_sequence == node.sequence,
            NodePairIntentRow.expires_at > datetime.fromtimestamp(now, UTC),
        )
        .limit(16)
    )
    for intent in intents:
        try:
            verify_request(envelope, public_key(intent.public_key), node_uuid=node.id, now=now)
        except ValueError:
            continue
        return JournalAuthority(node.id, True, False, int(intent.expires_at.timestamp()))
    raise JournalRejected("Current operator-pinned Node identity required")


def verify_delegated_authority(
    request: JournalRequest, core: Ed25519PublicKey, gateway: Ed25519PublicKey | None, now: int
) -> None:
    payload = request.payload
    if isinstance(payload, (ReserveOperation, ConfigureJournal)):
        command = payload.core_command
        if command.issued_at > now + 5 or command.expires_at <= now:
            raise JournalRejected("Fresh Core command required")
        verify_signature(core, payload.core_signature, command.signing_bytes())
    elif isinstance(payload, (ForwardTarget, AdmitForward)):
        proof = payload.proof
        if (
            gateway is None
            or proof.issued_at > now + 5
            or proof.expires_at <= now
            or not 0 < proof.expires_at - proof.issued_at <= 15
        ):
            raise JournalRejected("Fresh Gateway forwarding proof required")
        verify_signature(gateway, payload.gateway_signature, proof.signing_bytes())


def verify_signature(key: Ed25519PublicKey, signature: str, wire: bytes) -> None:
    try:
        key.verify(base64.b64decode(signature, validate=True), wire)
    except (ValueError, InvalidSignature):
        raise JournalRejected("Journal delegated signature rejected") from None


def delegated_deadline(request: JournalRequest) -> int:
    payload = request.payload
    if isinstance(payload, (ReserveOperation, ConfigureJournal)):
        return payload.core_command.expires_at
    if isinstance(payload, (ForwardTarget, AdmitForward)):
        return payload.proof.expires_at
    return request.expires_at


def require_configuration_owner(request: JournalRequest, node: NodeRow) -> None:
    if not isinstance(request.payload, ConfigureJournal):
        return
    record = request.payload.core_command.node_record
    if (
        record is None
        or record.id != node.id
        or record.scope.kind != node.scope
        or record.scope.owner_uuid != node.owner_uuid
        or record.created_at != node.created_at
    ):
        raise JournalRejected("Immutable node enrollment identity required")


async def require_commit_writer(
    session: SqlJournalSession, request: JournalRequest, result: JournalResult, now: int
) -> None:
    if request.action == "release":
        return
    lease = await session.lease()
    if lease is None:
        raise JournalConflict("Execution writer lease disappeared before commit")
    expected = result.lease_epoch if request.action == "acquire" else request.lease_epoch
    lease.require_writer(request.session_uuid, expected, now)


class SqlJournalSession:
    def __init__(self, tx: AsyncSession, node_uuid: UUID) -> None:
        self._tx, self._node = tx, node_uuid

    async def lease(self) -> WriterLease | None:
        row = await self._tx.get(NodeJournalLeaseRow, self._node)
        if row is None:
            return None
        return WriterLease(row.session_uuid, row.epoch, int(row.expires_at.timestamp()), row.cursor)

    async def save_lease(self, lease: WriterLease) -> None:
        row = await self._tx.get(NodeJournalLeaseRow, self._node)
        if row is None:
            row = NodeJournalLeaseRow(node_uuid=self._node, cursor=lease.cursor)
            self._tx.add(row)
        row.session_uuid, row.epoch = lease.session_uuid, lease.epoch
        row.expires_at = datetime.fromtimestamp(lease.expires_at, UTC)
        await self._tx.flush()

    async def configuration(self) -> JournalConfiguration | None:
        row = await self._tx.get(NodeJournalConfigurationRow, self._node)
        return (
            JournalConfiguration(
                sequence=row.sequence, record=NodeRecord.model_validate_json(row.record)
            )
            if row
            else None
        )

    async def save_configuration(self, configuration: JournalConfiguration) -> None:
        row = await self._tx.get(NodeJournalConfigurationRow, self._node)
        if row is None:
            row = NodeJournalConfigurationRow(node_uuid=self._node)
            self._tx.add(row)
        row.sequence, row.record = configuration.sequence, configuration.record.model_dump_json()
        await self._tx.flush()

    async def operation(self, operation: UUID) -> JournalOperation | None:
        row = await self._tx.get(NodeJournalOperationRow, (self._node, operation))
        return operation_record(row) if row else None

    async def latest(self, placement: UUID) -> JournalOperation | None:
        row = await self._tx.scalar(
            select(NodeJournalOperationRow)
            .where(
                NodeJournalOperationRow.node_uuid == self._node,
                NodeJournalOperationRow.placement_uuid == placement,
            )
            .order_by(NodeJournalOperationRow.sequence.desc())
            .limit(1)
        )
        return operation_record(row) if row else None

    async def save_operation(self, operation: JournalOperation) -> None:
        row = await self._tx.get(NodeJournalOperationRow, (self._node, UUID(operation.id)))
        if row is None:
            row = NodeJournalOperationRow(node_uuid=self._node, operation_uuid=UUID(operation.id))
            self._tx.add(row)
        row.placement_uuid, row.sequence = UUID(operation.placement), operation.sequence
        row.desired, row.fingerprint, row.phase = (
            operation.desired.model_dump_json(),
            operation.fingerprint,
            operation.phase,
        )
        row.previous, row.container, row.error = (
            operation.previous.model_dump_json() if operation.previous else None,
            operation.container,
            operation.error,
        )
        row.diagnostic = (
            operation.diagnostic.model_dump_json(exclude_none=True)
            if operation.diagnostic
            else None
        )
        await self._tx.flush()

    async def applied(self, placement: UUID) -> AppliedExecution | None:
        row = await self._tx.get(NodeJournalAppliedRow, (self._node, placement))
        return (
            AppliedExecution(Deployment.model_validate_json(row.spec), row.container)
            if row
            else None
        )

    async def save_applied(self, placement: UUID, applied: AppliedExecution) -> None:
        row = await self._tx.get(NodeJournalAppliedRow, (self._node, placement))
        if row is None:
            row = NodeJournalAppliedRow(node_uuid=self._node, placement_uuid=placement)
            self._tx.add(row)
        row.spec, row.container = applied.spec.model_dump_json(), applied.container
        await self._tx.flush()

    async def require_intent(self, command: ControlCommand) -> None:
        desired = command.deployment
        row = await self._tx.get(NodeOperationRow, command.operation_uuid)
        if (
            desired is None
            or row is None
            or row.node_uuid != self._node
            or row.placement_uuid != desired.id
            or row.sequence != command.sequence
            or row.fingerprint != desired.fingerprint
            or row.desired != desired
        ):
            raise JournalRejected("Current Core placement intent required")
        placement = await self._tx.get(NodeModuleRow, row.placement_uuid)
        if (
            placement is None
            or placement.node_uuid != self._node
            or placement.sequence != command.sequence
            or placement.project_uuid != desired.project_uuid
            or placement.artifact_key != desired.release.module
        ):
            raise JournalRejected("Current Core placement sequence required")

    async def event(self, fact: ConfigurationFact | OperationFact, now: int) -> None:
        lease = await self._tx.get(NodeJournalLeaseRow, self._node)
        if lease is None:
            raise JournalConflict("Execution writer lease disappeared")
        lease.cursor += 1
        self._tx.add(
            NodeJournalEventRow(
                node_uuid=self._node,
                cursor=lease.cursor,
                topic="configuration" if isinstance(fact, ConfigurationFact) else "operation",
                payload=event_payload(fact),
                created_at=datetime.fromtimestamp(now, UTC),
            )
        )
        await self._tx.execute(
            delete(NodeJournalEventRow).where(
                NodeJournalEventRow.node_uuid == self._node,
                NodeJournalEventRow.cursor <= lease.cursor - 2048,
            )
        )
        await self._tx.flush()

    async def events_after(self, cursor: int) -> tuple[JournalEvent, ...]:
        first = await self._tx.scalar(
            select(func.min(NodeJournalEventRow.cursor)).where(
                NodeJournalEventRow.node_uuid == self._node
            )
        )
        require_replay_window(cursor, first, await self.event_cursor())
        rows = await self._tx.scalars(
            select(NodeJournalEventRow)
            .where(NodeJournalEventRow.node_uuid == self._node, NodeJournalEventRow.cursor > cursor)
            .order_by(NodeJournalEventRow.cursor)
            .limit(128)
        )
        return tuple(
            JournalEvent.model_validate(
                {
                    "cursor": row.cursor,
                    "topic": row.topic,
                    "payload": json.loads(row.payload),
                    "created_at": row.created_at.isoformat(),
                }
            )
            for row in rows
        )

    async def event_cursor(self) -> int:
        lease = await self.lease()
        return lease.cursor if lease else 0

    async def admit_nonce(self, request: UUID, expires_at: int, now: int) -> None:
        await self._tx.execute(
            delete(NodeJournalAdmissionRow).where(
                NodeJournalAdmissionRow.node_uuid == self._node,
                NodeJournalAdmissionRow.expires_at <= now,
            )
        )
        count = await self._tx.scalar(
            select(func.count())
            .select_from(NodeJournalAdmissionRow)
            .where(NodeJournalAdmissionRow.node_uuid == self._node)
        )
        if count is not None and count >= 10000:
            raise JournalConflict("MCP admission window is full")
        if await self._tx.get(NodeJournalAdmissionRow, (self._node, request)) is not None:
            raise JournalConflict("MCP request already admitted; effects are never retried")
        self._tx.add(
            NodeJournalAdmissionRow(
                node_uuid=self._node, request_uuid=request, expires_at=expires_at
            )
        )
        await self._tx.flush()

    async def failed_candidate(self, value: FindFailedCandidate) -> JournalOperation | None:
        row = await self._tx.scalar(
            select(NodeJournalOperationRow)
            .where(
                NodeJournalOperationRow.node_uuid == self._node,
                NodeJournalOperationRow.placement_uuid == value.desired.id,
                NodeJournalOperationRow.container == value.container,
                NodeJournalOperationRow.fingerprint == value.fingerprint,
                NodeJournalOperationRow.sequence < value.before_sequence,
                NodeJournalOperationRow.phase == "failed",
            )
            .order_by(NodeJournalOperationRow.sequence.desc())
            .limit(1)
        )
        return operation_record(row) if row else None

    async def request_replay(
        self, request: JournalRequest, digest: str, now: int
    ) -> JournalResult | None:
        await self._tx.execute(
            delete(NodeJournalRequestRow).where(
                NodeJournalRequestRow.node_uuid == self._node,
                NodeJournalRequestRow.expires_at <= now,
            )
        )
        row = await self._tx.get(NodeJournalRequestRow, (self._node, request.request_uuid))
        if row is None:
            return None
        if row.fingerprint != digest or request.action == "admit_forward":
            raise JournalConflict("Journal request replay rejected")
        result = JournalResult.model_validate_json(row.response)
        lease = await self.lease()
        epoch = result.lease_epoch if request.action == "acquire" else request.lease_epoch
        if lease is None:
            raise JournalConflict("Execution writer lease missing")
        lease.require_writer(request.session_uuid, epoch, now)
        return result

    async def complete_request(
        self, request: JournalRequest, digest: str, result: JournalResult
    ) -> None:
        self._tx.add(
            NodeJournalRequestRow(
                node_uuid=self._node,
                request_uuid=request.request_uuid,
                fingerprint=digest,
                response=result.model_dump_json(),
                expires_at=request.expires_at,
            )
        )
        await self._tx.flush()


def operation_record(row: NodeJournalOperationRow) -> JournalOperation:
    return JournalOperation.model_validate(
        {
            "id": str(row.operation_uuid),
            "placement": str(row.placement_uuid),
            "sequence": row.sequence,
            "desired": Deployment.model_validate_json(row.desired),
            "fingerprint": row.fingerprint,
            "phase": row.phase,
            "previous": Deployment.model_validate_json(row.previous) if row.previous else None,
            "container": row.container,
            "error": row.error,
            "diagnostic": FailureDiagnostic.model_validate_json(row.diagnostic)
            if row.diagnostic
            else None,
        }
    )


def event_payload(fact: ConfigurationFact | OperationFact) -> str:
    if isinstance(fact, ConfigurationFact):
        return json.dumps(
            {"node_uuid": fact.node_uuid, "enabled": fact.enabled, "sequence": fact.sequence},
            separators=(",", ":"),
        )
    if fact.diagnostic is None:
        return json.dumps(
            {
                "operation_uuid": fact.operation_uuid,
                "sequence": fact.sequence,
                "phase": fact.phase,
                "error": fact.error,
            },
            separators=(",", ":"),
        )
    return json.dumps(
        {
            "operation_uuid": fact.operation_uuid,
            "sequence": fact.sequence,
            "phase": fact.phase,
            "error": fact.error,
            "diagnostic": fact.diagnostic.model_dump(mode="json", exclude_none=True),
        },
        separators=(",", ":"),
    )
