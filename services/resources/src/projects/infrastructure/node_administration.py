"""Current Platform proof decoding and owner SQL node configuration adapters."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from common.platform_db import PlatformDatabase
from node_protocol import NodeBudget as BudgetPayload
from node_protocol import ResourceLimits
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._node_persistence import NodeRow
from projects.application.node_administration import (
    ActorLookup,
    NodeAdministrationSession,
    NodeReceipt,
    NodeReplay,
)
from projects.domain.node_administration import (
    ManagedNode,
    NewNode,
    NodeBudget,
    NodeCapacity,
    NodeCommandIdentity,
    NodeConflict,
    NodeReceiptUnavailable,
    NodeScopeKind,
    OperatorEvidence,
    OperatorSelector,
)
from projects.infrastructure._session_bindings import _CipherSessionBinding
from projects.infrastructure.audit_records import NodeScopeAudit
from runtime_peer import PeerClient
from runtime_peer.transport import PeerRejected
from service_runtime._reference_bindings import _PeerBinding
from service_runtime.platform_db_mechanics import _DatabaseCipherBinding


class OperatorProofPayload(BaseModel):
    issuer: str
    subject: str
    actor_uuid: str
    project_uuid: str
    permissions: tuple[str, ...]
    role: str
    expires_at: datetime
    project_owner_kind: Literal["user", "team"] | None = None
    project_owner_uuid: str | None = None

    @field_validator("project_owner_uuid")
    @classmethod
    def canonical_owner(cls, value: str | None) -> str | None:
        if value is not None and str(UUID(value)) != value:
            raise ValueError("Canonical Platform project owner required")
        return value

    def evidence(self) -> OperatorEvidence:
        return OperatorEvidence(
            self.issuer,
            self.subject,
            self.actor_uuid,
            self.project_uuid,
            self.permissions,
            self.role,
            self.expires_at,
            self.project_owner_kind,
            UUID(self.project_owner_uuid) if self.project_owner_uuid is not None else None,
        )


def operator_reply(status: int, value: object) -> ActorLookup:
    if status != 200:
        return ActorLookup(status, None)
    try:
        return ActorLookup(status, OperatorProofPayload.model_validate(value).evidence())
    except ValidationError:
        return ActorLookup(status, None)


class PlatformActorSource(_PeerBinding[PeerClient]):
    async def read(self, selector: OperatorSelector) -> ActorLookup:
        try:
            _owner_reply = await self._peer.call(
                "/internal/v1/platform/oidc/actor-context",
                {
                    "issuer": selector.issuer,
                    "subject": selector.subject,
                    "project_uuid": str(selector.project_uuid),
                },
                decode=operator_reply,
            )
        except (PeerRejected, OSError, TimeoutError):
            return ActorLookup(503, None)
        return _owner_reply.body


def capacity_record(value: ResourceLimits) -> NodeCapacity:
    return NodeCapacity(value.memory_bytes, value.cpu_millis, value.pids)


def budget_record(value: BudgetPayload) -> NodeBudget:
    return NodeBudget(capacity_record(value.total), capacity_record(value.reserved))


def budget_payload(value: NodeBudget) -> BudgetPayload:
    return BudgetPayload(
        total=ResourceLimits(
            memory_bytes=value.total.memory_bytes,
            cpu_millis=value.total.cpu_millis,
            pids=value.total.pids,
        ),
        reserved=ResourceLimits(
            memory_bytes=value.reserved.memory_bytes,
            cpu_millis=value.reserved.cpu_millis,
            pids=value.reserved.pids,
        ),
    )


class NodeSummaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    scope: NodeScopeKind
    owner_uuid: str | None
    host_uuid: str
    runtime_uid: int
    endpoint: str
    budget: BudgetPayload
    enabled: bool
    paired: bool
    sequence: int
    last_seen_at: str | None
    created_at: str

    @classmethod
    def from_record(cls, node: ManagedNode) -> "NodeSummaryPayload":
        return cls(
            id=str(node.id),
            name=node.name,
            scope=node.scope,
            owner_uuid=str(node.owner_uuid) if node.owner_uuid else None,
            host_uuid=str(node.host_uuid),
            runtime_uid=node.runtime_uid,
            endpoint=node.endpoint,
            budget=budget_payload(node.budget),
            enabled=node.enabled,
            paired=node.paired,
            sequence=node.sequence,
            last_seen_at=node.last_seen_at.isoformat() if node.last_seen_at else None,
            created_at=node.created_at.isoformat(),
        )

    def record(self) -> ManagedNode:
        return ManagedNode(
            UUID(self.id),
            self.name,
            self.scope,
            UUID(self.owner_uuid) if self.owner_uuid else None,
            UUID(self.host_uuid),
            self.runtime_uid,
            self.endpoint,
            budget_record(self.budget),
            self.enabled,
            self.paired,
            self.sequence,
            datetime.fromisoformat(self.last_seen_at) if self.last_seen_at else None,
            datetime.fromisoformat(self.created_at),
        )


class NodeItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item: NodeSummaryPayload


class NodeReceiptPayload(BaseModel):
    operation: str
    digest: str
    result: NodeItemPayload


def node_record(row: NodeRow) -> ManagedNode:
    payload = NodeSummaryPayload.model_validate(
        {
            "id": str(row.id),
            "name": row.name,
            "scope": row.scope,
            "owner_uuid": str(row.owner_uuid) if row.owner_uuid else None,
            "host_uuid": str(row.host_uuid),
            "runtime_uid": row.runtime_uid,
            "endpoint": row.endpoint,
            "budget": row.budget,
            "enabled": row.enabled,
            "paired": bool(row.public_key),
            "sequence": row.sequence,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "created_at": row.created_at.isoformat(),
        }
    )
    return payload.record()


class SqlNodeAdministrationTransactions(_DatabaseCipherBinding[PlatformDatabase, Fernet]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[NodeAdministrationSession]:
        try:
            async with self._database.transaction() as tx:
                yield SqlNodeAdministrationSession(tx, self._cipher)
        except IntegrityError:
            raise NodeConflict(
                "Node identity or operation conflicts; retry the same operation"
            ) from None


class SqlNodeAdministrationSession(_CipherSessionBinding):
    async def nodes(self) -> tuple[ManagedNode, ...]:
        rows = await self._tx.scalars(
            select(NodeRow)
            .where(NodeRow.deleted_at.is_(None))
            .order_by(NodeRow.name, NodeRow.id)
            .limit(101)
        )
        return tuple(node_record(row) for row in rows)

    async def receipt(self, identity: NodeCommandIdentity) -> NodeReceipt | None:
        row = await self._tx.scalar(
            select(OwnerCommandRow)
            .where(
                OwnerCommandRow.operation_uuid == identity.operation_uuid,
                OwnerCommandRow.operation == "node." + identity.action,
            )
            .with_for_update()
        )
        return (
            NodeReceipt(
                row.fingerprint,
                row.actor_scope,
                row.project_scope,
                row.state,
                row.encrypted_outcome,
            )
            if row
            else None
        )

    def replay(self, receipt: NodeReceipt) -> NodeReplay:
        if receipt.encrypted_outcome is None:
            raise NodeReceiptUnavailable("Operation receipt unavailable")
        value = NodeReceiptPayload.model_validate_json(
            self._cipher.decrypt(receipt.encrypted_outcome.encode())
        )
        return NodeReplay(value.operation, value.digest, value.result.item.record())

    async def registered(self, node_uuid: UUID) -> bool:
        return await self._tx.get(NodeRow, node_uuid) is not None

    async def register(self, node: NewNode, now: datetime) -> ManagedNode:
        row = NodeRow(
            id=node.id,
            name=node.name,
            scope=node.scope,
            owner_uuid=node.owner_uuid,
            host_uuid=node.host_uuid,
            runtime_uid=node.runtime_uid,
            endpoint=node.endpoint,
            budget=budget_payload(node.budget),
            enabled=False,
            sequence=1,
            created_at=now,
        )
        self._tx.add(row)
        await self._tx.flush()
        return node_record(row)

    async def node(self, node_uuid: UUID) -> ManagedNode | None:
        row = await self._tx.scalar(
            select(NodeRow)
            .where(NodeRow.id == node_uuid, NodeRow.deleted_at.is_(None))
            .with_for_update()
        )
        return node_record(row) if row else None

    async def save(self, node: ManagedNode) -> None:
        row = await self._tx.get(NodeRow, node.id)
        if row is None:
            raise NodeConflict("Node disappeared during configuration")
        row.name, row.enabled, row.sequence = node.name, node.enabled, node.sequence
        await self._tx.flush()

    async def complete(
        self, identity: NodeCommandIdentity, node: ManagedNode, now: datetime
    ) -> None:
        payload = NodeReceiptPayload(
            operation=str(identity.operation_uuid),
            digest=identity.fingerprint,
            result=NodeItemPayload(item=NodeSummaryPayload.from_record(node)),
        )
        self._tx.add(
            OwnerCommandRow(
                operation_uuid=identity.operation_uuid,
                actor_scope=str(identity.actor_uuid),
                project_scope=str(identity.project_uuid),
                operation="node." + identity.action,
                key=str(identity.operation_uuid),
                fingerprint=identity.fingerprint,
                expected_owner_revision=str(identity.expected_sequence or 0),
                state="completed",
                encrypted_outcome=self._cipher.encrypt(payload.model_dump_json().encode()).decode(),
                expires_at=now + timedelta(days=7),
            )
        )
        self._tx.add(
            OwnerAuditRow(
                operation_uuid=identity.operation_uuid,
                actor_user_id=identity.actor_uuid,
                project_id=identity.project_uuid,
                action="node." + identity.action,
                object_id=str(node.id),
                owner_revision=str(node.sequence),
                details=NodeScopeAudit(scope=node.scope),
            )
        )
