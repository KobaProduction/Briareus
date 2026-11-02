"""A recovery retry reads the committed intent and never dispatches Apply twice."""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from projects._node_persistence import (
    ModuleArtifactRow,
    ModuleReleaseRow,
    NodeModuleRow,
    NodeOperationRow,
    NodeRow,
    NodeStorageRow,
)
from projects.domain.node_administration import NodeActor, OperatorAuthority
from projects.module_placements import PlacementManager
from projects.presentation.node_commands import NodeCommand
from sqlalchemy import Select

from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.management import ModuleCommand, PlacementRecovery
from projects._catalog_ledger import OwnerAuditRow


class RecoveryCommandSQL:
    def __init__(self, spec: Deployment, actor: UUID) -> None:
        assert spec.workspace is not None
        release_id = uuid4()
        self.placement = NodeModuleRow(
            id=spec.id,
            project_uuid=spec.project_uuid,
            node_uuid=spec.node_uuid,
            artifact_key="files",
            sequence=3,
            state="ready",
            applied_release_uuid=release_id,
            storage_uuid=spec.workspace.id,
        )
        self.prior = NodeOperationRow(
            id=uuid4(),
            placement_uuid=spec.id,
            node_uuid=spec.node_uuid,
            actor_uuid=actor,
            sequence=3,
            phase="succeeded",
            error_code=None,
            desired=spec,
            previous=None,
        )
        self.rows: tuple[NodeRow | ModuleReleaseRow | ModuleArtifactRow | NodeStorageRow, ...] = (
            NodeRow(
                id=spec.node_uuid,
                scope="personal",
                owner_uuid=actor,
                enabled=True,
                deleted_at=None,
                public_key="pinned",
            ),
            ModuleReleaseRow(
                id=release_id,
                state="published",
                artifact_key="files",
                image_reference=spec.release.image,
            ),
            ModuleArtifactRow(key="files", enabled=True),
            NodeStorageRow(
                id=spec.workspace.id,
                node_uuid=spec.node_uuid,
                project_uuid=spec.project_uuid,
                retention="persistent",
            ),
        )
        self.operations: dict[UUID, NodeOperationRow] = {}
        self.audits: list[OwnerAuditRow] = []

    async def scalar(
        self, statement: Select[tuple[object]]
    ) -> NodeModuleRow | NodeOperationRow | None:
        if "resources.node_modules" in str(statement):
            return self.placement
        if "resources.node_operations" in str(statement):
            return self.prior
        return None

    async def get[RowT](self, model: type[RowT], key: UUID | str) -> RowT | None:
        for row in (*self.rows, *self.operations.values()):
            identifier = row.key if isinstance(row, ModuleArtifactRow) else row.id
            if isinstance(row, model) and identifier == key:
                return row
        return None

    def add(self, row: NodeOperationRow | OwnerAuditRow) -> None:
        if isinstance(row, NodeOperationRow):
            self.operations[row.id] = row
        else:
            self.audits.append(row)

    async def flush(self) -> None:
        for row in self.operations.values():
            # SQLAlchemy assigns these defaults during a real database flush.
            row.updated_at = datetime.now(UTC)


class RecoverCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_signed_intent_preserves_exact_spec_and_retry_never_redispatches(
        self,
    ) -> None:
        actor = uuid4()
        spec = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=uuid4(),
            workspace=WorkspaceMount(id=uuid4()),
            release=ModuleRelease(
                module="files",
                image="registry.example/files@sha256:" + "a" * 64,
                lifecycle="stateless",
            ),
            limits=ResourceLimits(memory_bytes=256 * 1024**2, cpu_millis=200, pids=64),
        )
        tx = RecoveryCommandSQL(spec, actor)
        database = PlatformDatabase(
            PlatformDatabaseSettings.model_validate(
                {
                    "POSTGRES_HOST": "127.0.0.1",
                    "POSTGRES_PORT": 1,
                    "POSTGRES_DB": "briareus_resources",
                    "POSTGRES_USER": "fixture",
                    "POSTGRES_PASSWORD": uuid4().hex,
                }
            )
        )
        self.addAsyncCleanup(database.close)

        @asynccontextmanager
        async def transaction() -> AsyncIterator[RecoveryCommandSQL]:
            yield tx

        self.enterContext(patch.object(database, "transaction", transaction))

        async def authorize(_command: NodeCommand) -> OperatorAuthority:
            return OperatorAuthority(
                NodeActor(actor, "user", actor), datetime.now(UTC) + timedelta(seconds=20)
            )

        manager = PlacementManager(lambda: database, authorize)
        self.addAsyncCleanup(manager.close)
        command = NodeCommand(
            issuer="https://issuer.example",
            subject="fixture",
            actor_uuid=actor,
            project_uuid=spec.project_uuid,
            operation_uuid=uuid4(),
            action="modules",
            identity_expires_at=datetime.now(UTC) + timedelta(seconds=20),
            module=ModuleCommand(
                action="recover", recover=PlacementRecovery(id=spec.id, expected_sequence=3)
            ),
        )
        with (
            patch.object(manager, "start") as dispatch,
            patch(
                "projects.infrastructure.placement_mutations.operation_diagnostic",
                AsyncMock(return_value=None),
            ),
        ):
            first = await manager.recover(command, command.identity_expires_at)
            replay = await manager.recover(command, command.identity_expires_at)
        saved = tx.operations[command.operation_uuid]
        self.assertEqual(saved.desired, spec)
        self.assertEqual(saved.previous, saved.desired)
        self.assertEqual(saved.fingerprint, spec.fingerprint)
        self.assertEqual(saved.sequence, 4)
        self.assertEqual([call.args[2] for call in dispatch.call_args_list], [True, False])
        self.assertEqual(first.body, replay.body)
        self.assertEqual(len(tx.operations), 1)
        self.assertEqual(len(tx.audits), 1)
