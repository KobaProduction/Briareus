"""Fresh runtime observation never replaces owner, storage and image checks."""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects._node_persistence import ModuleReleaseRow, NodeModuleRow, NodeOperationRow, NodeRow
from projects.domain.node_administration import NodeActor, OperatorAuthority
from projects.infrastructure.audit_records import PlacementAudit
from projects.module_placements import PlacementManager
from projects.node_control import NodeControl
from projects.placement_recovery import current_spec, verified_restoration
from projects.presentation.node_commands import NodeCommand
from sqlalchemy import Select

from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
from node_protocol.domain.observations import (
    NodeInventory,
    NodeOperation,
    ObservedLimits,
    ObservedModule,
)
from projects._catalog_ledger import OwnerAuditRow


class RecoverySQL:
    def __init__(self, owner: PlacementRecoveryTests) -> None:
        self.test = owner

    async def scalar(self, _query: Select[tuple[NodeOperationRow]]) -> NodeOperationRow:
        return self.test.row

    async def get[RowT](self, model: type[RowT], key: UUID) -> RowT | None:
        for row in (self.test.row, self.test.placement, self.test.release, self.test.node):
            if isinstance(row, model) and row.id == key:
                return row
        return None

    def add(self, record: OwnerAuditRow) -> None:
        self.test.audit.append(record)


class PlacementRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.old = Deployment(
            id=uuid4(),
            node_uuid=uuid4(),
            project_uuid=uuid4(),
            workspace=WorkspaceMount(id=uuid4()),
            release=ModuleRelease(
                module="svc",
                image="registry.example/svc@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=1024**3, cpu_millis=500, pids=128),
        )
        assert self.old.workspace is not None
        self.new = self.old.model_copy(
            update={"limits": self.old.limits.model_copy(update={"cpu_millis": 600})}
        )
        self.row = NodeOperationRow(
            id=uuid4(),
            node_uuid=self.old.node_uuid,
            placement_uuid=self.old.id,
            actor_uuid=uuid4(),
            sequence=2,
            phase="checking",
            error_code=None,
            previous=self.old,
            desired=self.new,
            updated_at=datetime.now(UTC),
        )
        self.placement = NodeModuleRow(
            id=self.old.id,
            node_uuid=self.old.node_uuid,
            project_uuid=self.old.project_uuid,
            artifact_key="svc",
            storage_uuid=self.old.workspace.id,
            sequence=2,
            state="updating",
            applied_release_uuid=uuid4(),
            desired_release_uuid=uuid4(),
            limits=self.new.limits,
        )
        self.release = ModuleReleaseRow(
            id=self.placement.applied_release_uuid,
            image_reference=self.old.release.image,
            artifact_key="svc",
        )
        self.receipt = NodeOperation(self.row.id, 2, "failed", "UPDATE_FAILED")
        self.inventory = NodeInventory(
            self.old.node_uuid,
            True,
            0,
            7,
            (
                ObservedModule(
                    self.old.id,
                    self.old.fingerprint,
                    True,
                    True,
                    ObservedLimits(
                        self.old.limits.memory_bytes,
                        self.old.limits.cpu_millis,
                        self.old.limits.pids,
                    ),
                ),
            ),
        )
        self.audit: list[OwnerAuditRow] = []
        self.node = NodeRow(
            id=self.old.node_uuid,
            sequence=7,
            deleted_at=None,
            enabled=True,
            public_key="pinned-node-test-key",
            endpoint="https://node.example",
        )
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

        @asynccontextmanager
        async def transaction() -> AsyncIterator[RecoverySQL]:
            yield RecoverySQL(self)

        self.enterContext(patch.object(database, "transaction", transaction))
        self.addAsyncCleanup(database.close)
        self.manager = PlacementManager(lambda: database, self.authorize)
        self.addAsyncCleanup(self.manager.close)

    async def authorize(self, _command: NodeCommand) -> OperatorAuthority:
        return OperatorAuthority(
            NodeActor(self.row.actor_uuid, None, None), datetime.now(UTC) + timedelta(seconds=20)
        )

    async def save(self, inventory: NodeInventory | None) -> bool:
        with patch("projects.module_placements.operation_diagnostic", AsyncMock(return_value=None)):
            return await self.manager.save(self.row.id, self.receipt, inventory=inventory)

    async def test_verified_previous_becomes_ready_but_failed_update_is_preserved(self) -> None:
        self.assertTrue(await self.save(self.inventory))
        self.assertEqual((self.row.phase, self.row.error_code), ("failed", "UPDATE_FAILED"))
        self.assertEqual(self.placement.state, "ready")
        self.assertEqual(self.placement.limits, self.old.limits)
        self.assertEqual(current_spec(self.placement, self.row), self.old)
        details = self.audit[0].details
        assert isinstance(details, PlacementAudit)
        self.assertEqual(details.restored_fingerprint, self.old.fingerprint)

    async def test_failed_receipt_stays_closed_until_explicit_reconciliation(
        self,
    ) -> None:
        await self.save(None)
        self.assertEqual(self.placement.state, "failed")
        await self.save(self.inventory)
        self.assertEqual(self.placement.state, "ready")

    async def test_mismatched_applied_image_cannot_restore(self) -> None:
        self.release.image_reference = "registry.example/svc@sha256:" + "b" * 64
        await self.save(self.inventory)
        self.assertEqual(self.placement.state, "failed")

    def test_wrong_node_ambiguous_unready_wrong_fingerprint_and_limits_are_rejected(self) -> None:
        item = self.inventory.items[0]
        invalid = (
            replace(self.inventory, node_uuid=uuid4()),
            replace(self.inventory, sequence=6),
            replace(self.inventory, enabled=False),
            replace(self.inventory, items=(item, item)),
            replace(self.inventory, items=(replace(item, ready=False),)),
            replace(self.inventory, items=(replace(item, fingerprint=self.new.fingerprint),)),
            replace(
                self.inventory, items=(replace(item, limits=replace(item.limits, cpu_millis=600)),)
            ),
        )
        for inventory in invalid:
            with self.subTest(inventory=inventory):
                self.assertIsNone(
                    verified_restoration(
                        self.placement, self.row, self.receipt, inventory, node=self.node
                    )
                )
        self.placement.storage_uuid = uuid4()
        self.assertIsNone(
            verified_restoration(
                self.placement, self.row, self.receipt, self.inventory, node=self.node
            )
        )

    async def test_stale_operation_or_changed_terminal_receipt_never_changes_projection(
        self,
    ) -> None:
        self.placement.sequence = 3
        with self.assertRaises(ValueError):
            await self.save(self.inventory)
        self.assertEqual(self.placement.state, "updating")
        self.placement.sequence = 2
        self.row.phase, self.row.error_code = "failed", "ROLLBACK_FAILED"
        with self.assertRaises(ValueError):
            await self.save(self.inventory)
        self.assertEqual(self.placement.state, "updating")

    async def test_terminal_reconcile_fetches_new_inventory_after_failed_receipt_without_apply(
        self,
    ) -> None:
        self.row.phase, self.row.error_code, self.placement.state = (
            "failed",
            "UPDATE_FAILED",
            "failed",
        )
        remote = NodeControl(Ed25519PrivateKey.generate(), frozenset({self.node.endpoint}))
        self.addAsyncCleanup(remote.close)
        self.manager.remote = remote
        command = NodeCommand(
            issuer="https://issuer.example",
            subject="fixture",
            actor_uuid=self.row.actor_uuid,
            project_uuid=self.old.project_uuid,
            operation_uuid=uuid4(),
            action="modules",
            identity_expires_at=datetime.now(UTC) + timedelta(seconds=20),
        )
        with (
            patch.object(
                remote,
                "call",
                AsyncMock(side_effect=(self.inventory, self.receipt, self.inventory)),
            ) as calls,
            patch.object(
                remote,
                "watch",
                side_effect=AssertionError("Terminal receipt must not watch or apply"),
            ),
            patch("projects.module_placements.operation_diagnostic", AsyncMock(return_value=None)),
        ):
            await self.manager.run(command, self.row.id, False)
        self.assertEqual(
            [call.kwargs.get("action", "inventory") for call in calls.call_args_list],
            ["inventory", "status", "inventory"],
        )
        self.assertEqual(self.placement.state, "ready")
