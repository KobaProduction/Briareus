"""SQL workspace owner storage, encrypted replay, and audit in one transaction."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._node_persistence import NodeRow, NodeStorageRow
from projects.application.project_workspaces import WorkspaceReceipt, WorkspaceSession
from projects.domain.project_workspaces import (
    ProjectWorkspace,
    WorkspaceIdentity,
    WorkspaceNode,
    WorkspaceRejected,
    WorkspaceReplay,
)
from projects.infrastructure.audit_records import WorkspaceAudit
from service_runtime.platform_db_mechanics import _DatabaseCipherBinding, _SessionCipherBinding

WORKSPACE_ACTION = "node.workspace.ensure"


class WorkspacePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    node_uuid: str
    project_uuid: str
    purpose: str
    retention: str

    @classmethod
    def from_record(cls, workspace: ProjectWorkspace) -> "WorkspacePayload":
        return cls(
            id=str(workspace.id),
            node_uuid=str(workspace.node_uuid),
            project_uuid=str(workspace.project_uuid),
            purpose=workspace.purpose,
            retention=workspace.retention,
        )

    def record(self) -> ProjectWorkspace:
        if any(str(UUID(value)) != value for value in (self.id, self.node_uuid, self.project_uuid)):
            raise ValueError("Canonical workspace identity required")
        return ProjectWorkspace(
            UUID(self.id),
            UUID(self.node_uuid),
            UUID(self.project_uuid),
            self.purpose,
            self.retention,
        )


class WorkspaceItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item: WorkspacePayload


class WorkspaceReceiptPayload(BaseModel):
    operation: str
    digest: str
    result: WorkspaceItemPayload


def workspace_record(row: NodeStorageRow) -> ProjectWorkspace:
    return ProjectWorkspace(row.id, row.node_uuid, row.project_uuid, row.purpose, row.retention)


class SqlWorkspaceTransactions(_DatabaseCipherBinding[PlatformDatabase, Fernet]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[WorkspaceSession]:
        try:
            async with self._database.transaction() as tx:
                yield SqlWorkspaceSession(tx, self._cipher)
        except IntegrityError:
            raise WorkspaceRejected(
                "Concurrent workspace operation; retry the same operation"
            ) from None


class SqlWorkspaceSession(_SessionCipherBinding[AsyncSession, Fernet]):
    async def lock_node(self, identity: WorkspaceIdentity) -> WorkspaceNode | None:
        row = await self._session.scalar(
            select(NodeRow).where(NodeRow.id == identity.node_uuid).with_for_update()
        )
        if row is None:
            return None
        return WorkspaceNode(
            row.id,
            row.scope,
            row.owner_uuid,
            row.enabled,
            row.deleted_at is not None,
            bool(row.public_key),
        )

    async def workspace(self, identity: WorkspaceIdentity) -> ProjectWorkspace | None:
        row = await self._session.scalar(
            select(NodeStorageRow).where(
                NodeStorageRow.node_uuid == identity.node_uuid,
                NodeStorageRow.project_uuid == identity.project_uuid,
                NodeStorageRow.purpose == "workspace",
            )
        )
        return workspace_record(row) if row is not None else None

    async def receipt(self, identity: WorkspaceIdentity) -> WorkspaceReceipt | None:
        row = await self._session.scalar(
            select(OwnerCommandRow).where(
                OwnerCommandRow.operation_uuid == identity.operation_uuid,
                OwnerCommandRow.operation == WORKSPACE_ACTION,
            )
        )
        if row is None:
            return None
        return WorkspaceReceipt(
            row.actor_scope, row.project_scope, row.fingerprint, row.state, row.encrypted_outcome
        )

    def replay(self, receipt: WorkspaceReceipt) -> WorkspaceReplay:
        if receipt.encrypted_outcome is None:
            raise WorkspaceRejected("Current workspace receipt unavailable")
        plaintext = self._cipher.decrypt(receipt.encrypted_outcome.encode())
        try:
            payload = WorkspaceReceiptPayload.model_validate_json(plaintext)
            return WorkspaceReplay(payload.operation, payload.digest, payload.result.item.record())
        except (ValidationError, ValueError):
            raise WorkspaceRejected("Current workspace receipt unavailable") from None

    async def create(self, identity: WorkspaceIdentity) -> ProjectWorkspace:
        row = NodeStorageRow(
            id=uuid4(),
            node_uuid=identity.node_uuid,
            project_uuid=identity.project_uuid,
            purpose="workspace",
            quota_bytes=1024**3,
            retention="persistent",
        )
        self._session.add(row)
        await self._session.flush()
        return workspace_record(row)

    async def complete(
        self, identity: WorkspaceIdentity, workspace: ProjectWorkspace, now: datetime
    ) -> None:
        payload = WorkspaceReceiptPayload(
            operation=str(identity.operation_uuid),
            digest=identity.fingerprint,
            result=WorkspaceItemPayload(item=WorkspacePayload.from_record(workspace)),
        )
        self._session.add(
            OwnerCommandRow(
                operation_uuid=identity.operation_uuid,
                actor_scope=str(identity.actor_uuid),
                project_scope=str(identity.project_uuid),
                operation=WORKSPACE_ACTION,
                key=str(identity.operation_uuid),
                fingerprint=identity.fingerprint,
                expected_owner_revision="0",
                state="completed",
                expires_at=now + timedelta(days=7),
                encrypted_outcome=self._cipher.encrypt(payload.model_dump_json().encode()).decode(),
            )
        )
        self._session.add(
            OwnerAuditRow(
                operation_uuid=identity.operation_uuid,
                actor_user_id=identity.actor_uuid,
                project_id=identity.project_uuid,
                action=WORKSPACE_ACTION,
                object_id=str(workspace.id),
                owner_revision="1",
                details=WorkspaceAudit(node_uuid=identity.node_uuid),
            )
        )
