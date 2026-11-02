"""SQL enrollment receipts, compare-and-set updates and trusted key decoding."""

from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from node_protocol.replies import NodeReplyVerifier
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._journal_persistence import NodePairIntentRow
from projects._node_persistence import NodeRow
from projects.application.node_enrollment import (
    EnrollmentAcknowledgement,
    EnrollmentRequest,
    EnrollmentTarget,
)
from projects.domain.node_administration import (
    ManagedNode,
    NodeConflict,
    NodeForbidden,
    NodeMissing,
    NodeReceiptUnavailable,
)
from projects.infrastructure.audit_records import NodeScopeAudit
from projects.infrastructure.node_administration import (
    NodeItemPayload,
    NodeReceiptPayload,
    NodeSummaryPayload,
    node_record,
)
from projects.infrastructure.node_control import node_record as execution_record
from projects.infrastructure.node_pairing import remember_pair_intent
from service_runtime.platform_db_mechanics import _DatabaseCipherBinding


def canonical_node_key(value: str) -> str:
    verifier = NodeReplyVerifier(value.encode())
    return verifier.key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


class SqlEnrollmentStore(_DatabaseCipherBinding[PlatformDatabase, Fernet]):
    def _replay(self, row: OwnerCommandRow, request: EnrollmentRequest) -> ManagedNode:
        if (
            row.fingerprint != request.fingerprint
            or row.actor_scope != str(request.actor_uuid)
            or row.project_scope != str(request.project_uuid)
            or row.state != "completed"
        ):
            raise NodeConflict("Operation identity conflict")
        if row.encrypted_outcome is None:
            raise NodeReceiptUnavailable("Operation receipt unavailable")
        value = NodeReceiptPayload.model_validate_json(
            self._cipher.decrypt(row.encrypted_outcome.encode())
        )
        if value.digest != request.fingerprint or value.operation != str(request.operation_uuid):
            raise NodeReceiptUnavailable("Operation receipt unavailable")
        return value.result.item.record()

    async def read(self, request: EnrollmentRequest) -> ManagedNode | EnrollmentTarget:
        async with self._database.transaction() as tx:
            existing = await tx.scalar(
                select(OwnerCommandRow).where(
                    OwnerCommandRow.operation_uuid == request.operation_uuid,
                    OwnerCommandRow.operation == request.operation,
                )
            )
            if existing is not None:
                return self._replay(existing, request)
            row = await tx.get(NodeRow, request.node_uuid)
            if row is None or row.deleted_at is not None:
                raise NodeMissing("Node not found")
            if row.sequence != request.expected_sequence:
                raise NodeConflict("Node configuration changed")
            return EnrollmentTarget(
                execution_record(row), row.endpoint, row.public_key, row.runtime_uid
            )

    async def remember_pair(
        self,
        request: EnrollmentRequest,
        target: EnrollmentTarget,
        public_key: str,
        expiry: datetime,
    ) -> None:
        await remember_pair_intent(
            self._database,
            node_uuid=target.record.id,
            operation_uuid=request.operation_uuid,
            actor_uuid=request.actor_uuid,
            project_uuid=request.project_uuid,
            expected_sequence=request.expected_sequence,
            endpoint=target.endpoint,
            pinned=target.pinned,
            public_key=public_key,
            fingerprint=request.fingerprint,
            expiry=expiry,
        )

    async def complete(
        self,
        request: EnrollmentRequest,
        target: EnrollmentTarget,
        acknowledgement: EnrollmentAcknowledgement,
        expiry: datetime,
    ) -> ManagedNode:
        async with self._database.transaction() as tx:
            row = await tx.scalar(
                select(NodeRow)
                .where(NodeRow.id == request.node_uuid, NodeRow.deleted_at.is_(None))
                .with_for_update()
            )
            if (
                row is None
                or row.sequence != request.expected_sequence
                or row.endpoint != target.endpoint
                or row.public_key != target.pinned
            ):
                raise NodeConflict("Node configuration changed; reconcile enrollment")
            if expiry <= datetime.now(UTC):
                raise NodeForbidden("Platform proof expired")
            await self._apply(tx, row, request, acknowledgement)
            result = node_record(row)
            self._complete_receipt(tx, request, result)
        return result

    async def _apply(
        self,
        tx: AsyncSession,
        row: NodeRow,
        request: EnrollmentRequest,
        acknowledgement: EnrollmentAcknowledgement,
    ) -> None:
        row.public_key = acknowledgement.public_key
        if request.action == "pair":
            intent = await tx.get(NodePairIntentRow, request.operation_uuid)
            if intent is not None:
                await tx.delete(intent)
        row.enabled = True if request.action == "enable" else row.enabled
        if request.action == "budget":
            if acknowledgement.budget is None:
                raise ValueError("Acknowledged node budget required")
            row.budget = acknowledgement.budget
        row.last_seen_at = datetime.now(UTC)
        row.sequence += 1
        await tx.flush()

    def _complete_receipt(
        self, tx: AsyncSession, request: EnrollmentRequest, node: ManagedNode
    ) -> None:
        payload = NodeReceiptPayload(
            operation=str(request.operation_uuid),
            digest=request.fingerprint,
            result=NodeItemPayload(item=NodeSummaryPayload.from_record(node)),
        )
        tx.add(
            OwnerCommandRow(
                operation_uuid=request.operation_uuid,
                actor_scope=str(request.actor_uuid),
                project_scope=str(request.project_uuid),
                operation=request.operation,
                key=str(request.operation_uuid),
                fingerprint=request.fingerprint,
                expected_owner_revision=str(request.expected_sequence),
                state="completed",
                encrypted_outcome=self._cipher.encrypt(payload.model_dump_json().encode()).decode(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        tx.add(
            OwnerAuditRow(
                operation_uuid=request.operation_uuid,
                actor_user_id=request.actor_uuid,
                project_id=request.project_uuid,
                action=request.operation,
                object_id=str(node.id),
                owner_revision=str(node.sequence),
                details=NodeScopeAudit(scope=node.scope),
            )
        )
