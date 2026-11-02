"""Disposable Resources DB placement intent, workspace ownership and recovery boundaries."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from node_control_fixture import ControlCall, ControlFixture
from projects._node_persistence import (
    ModuleArtifactRow,
    ModuleReleaseRow,
    NodeModuleRow,
    NodeOperationRow,
    NodeRow,
    NodeStorageRow,
)
from projects.infrastructure.catalog_records import InputPayload, artifact_definition
from projects.infrastructure.node_storage_models import (
    ArtifactConfigurationContract,
    ArtifactStorageContract,
)
from projects.presentation.node_commands import NodeCommand
from test_node_management import NodeManagementFixture

from node_protocol import Deployment, ResourceLimits
from node_protocol.catalog import ARTIFACTS
from node_protocol.domain.observations import NodeInventory, NodeOperation, NodeReply
from node_protocol.management import ModuleCommand, PlacementInput, PlacementUpdate


@unittest.skipUnless(
    os.environ.get("NODE_SCHEMA_ACCEPTANCE") == "1", "Explicit disposable Resources DB required"
)
class PlacementTests(NodeManagementFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        register = self.command(action="register", registration=self.registration())
        assert register.registration is not None
        await self.endpoint(register, self.request)
        self.node = register.registration.id
        self.release = uuid4()
        self.lose_acknowledgement = False
        self.spec: Deployment

        def respond(call: ControlCall) -> NodeReply:
            if self.lose_acknowledgement:
                raise ValueError("Remote acknowledgement lost")
            if call.action == "apply":
                assert call.deployment is not None
                self.spec = call.deployment
                return NodeOperation(call.operation_uuid, call.sequence, "queued", None)
            if call.action == "status":
                return NodeOperation(call.operation_uuid, call.sequence, "succeeded", None)
            return NodeInventory(call.node_uuid, True, 0, call.sequence, ())

        remote = ControlFixture(respond)
        self.addAsyncCleanup(remote.close)
        self.calls = remote.calls
        self.router.node_placements.remote = remote
        async with self.db.transaction() as tx:
            node = await tx.get(NodeRow, self.node)
            assert node is not None
            node.enabled = True
            node.public_key = "pinned-runtime-fixture"
            artifact = await tx.get(ModuleArtifactRow, "files")
            if artifact is None:
                tx.add(
                    ModuleArtifactRow(
                        key="files",
                        name="Files",
                        inputs=InputPayload.from_record(
                            artifact_definition(ARTIFACTS["files"]).inputs
                        ),
                        configuration_contract=ArtifactConfigurationContract(
                            kind="approved_node_adapter"
                        ),
                        storage_contract=ArtifactStorageContract(
                            workspace=True, purpose="workspace"
                        ),
                        enabled=True,
                    )
                )
                await tx.flush()
            else:
                artifact.inputs = InputPayload.from_record(
                    artifact_definition(ARTIFACTS["files"]).inputs
                )
                artifact.enabled = True
            tx.add(
                ModuleReleaseRow(
                    id=self.release,
                    artifact_key="files",
                    source_commit=uuid4().hex + "a" * 8,
                    input_fingerprint=uuid4().hex + uuid4().hex,
                    platform="linux/amd64",
                    state="published",
                    image_reference="registry.example/files@sha256:" + "b" * 64,
                    storage_compatibility="workspace",
                )
            )

    def intent(self) -> NodeCommand:
        return self.command(
            action="modules",
            module=ModuleCommand(
                action="place",
                placement=PlacementInput(
                    id=uuid4(),
                    node_uuid=self.node,
                    release_uuid=self.release,
                    name="Project Files",
                    limits=ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=200, pids=64),
                ),
            ),
        )

    async def place(self, command: NodeCommand) -> None:
        public = (
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "public.key"
            path.write_bytes(public)
            with patch.dict(os.environ, {"RESOURCES_ACCESS_VERIFY_KEY_FILE": str(path)}):
                await self.endpoint(command, self.request)
                await asyncio.gather(*list(self.router.node_placements.tasks.values()))

    async def test_intent_dispatch_and_workspace_are_durable_and_replay_safe(self) -> None:
        command = self.intent()
        assert command.module is not None and command.module.placement is not None
        await self.place(command)
        async with self.db.transaction() as tx:
            operation = await tx.get(NodeOperationRow, command.operation_uuid)
            placement = await tx.get(NodeModuleRow, command.module.placement.id)
            assert operation is not None and placement is not None
            storage = await tx.get(NodeStorageRow, placement.storage_uuid)
            assert storage is not None and self.spec.workspace is not None
            self.assertEqual(operation.phase, "succeeded")
            self.assertEqual(placement.state, "ready")
            self.assertEqual(placement.applied_release_uuid, self.release)
            self.assertEqual(storage.project_uuid, self.project)
            self.assertEqual(storage.node_uuid, self.node)
            self.assertEqual(self.spec.workspace.id, storage.id)
        before = len(self.calls)
        await self.place(command)
        self.assertEqual(len(self.calls), before)
        other = self.intent()
        with self.assertRaises(HTTPException) as denied:
            await self.place(other)
        self.assertEqual(denied.exception.status_code, 409)

    async def test_ack_loss_stays_unknown_and_reconcile_never_reissues_apply(self) -> None:
        command = self.intent()
        self.lose_acknowledgement = True
        await self.place(command)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeOperationRow, command.operation_uuid)
            assert row is not None
            self.assertEqual(row.phase, "unknown")
            self.assertEqual(row.error_code, "NODE_RECONCILIATION_REQUIRED")
        self.lose_acknowledgement = False
        reconcile = self.command(
            action="modules",
            module=ModuleCommand(action="reconcile", target_operation_uuid=command.operation_uuid),
        )
        before = sum(item.action == "apply" for item in self.calls)
        await self.place(command)
        self.assertEqual(sum(item.action == "apply" for item in self.calls), before)
        await self.endpoint(reconcile, self.request)
        await asyncio.gather(*list(self.router.node_placements.tasks.values()))
        self.assertEqual(sum(item.action == "apply" for item in self.calls), before)
        async with self.db.transaction() as tx:
            operation = await tx.get(NodeOperationRow, command.operation_uuid)
            assert operation is not None
            self.assertEqual(operation.phase, "succeeded")

    async def test_orphaned_operation_exposes_observe_only_recovery(self) -> None:
        command = self.intent()
        self.lose_acknowledgement = True
        await self.place(command)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeOperationRow, command.operation_uuid)
            assert row is not None
            row.phase = "checking"
            row.error_code = None
        listing = self.command(
            action="modules", module=ModuleCommand(action="placements", node_uuid=self.node)
        )
        response = json.loads(bytes((await self.endpoint(listing, self.request)).body))
        self.assertTrue(response["items"][0]["operation"]["reconciliation_required"])

    async def test_changed_artifact_definition_denies_before_remote_effects(self) -> None:
        async with self.db.transaction() as tx:
            artifact = await tx.get(ModuleArtifactRow, "files")
            assert artifact is not None
            original = artifact.inputs
            assert original is not None
            artifact.inputs = original.model_copy(update={"paths": ("unapproved/input",)})
        try:
            with self.assertRaises(HTTPException) as denied:
                await self.place(self.intent())
            self.assertEqual(denied.exception.status_code, 409)
            self.assertEqual(self.calls, [])
        finally:
            async with self.db.transaction() as tx:
                artifact = await tx.get(ModuleArtifactRow, "files")
                assert artifact is not None
                artifact.inputs = original

    async def test_update_preserves_project_workspace_limits_and_is_replay_safe(self) -> None:
        command = self.intent()
        assert command.module is not None and command.module.placement is not None
        await self.place(command)
        before = self.spec
        release = uuid4()
        async with self.db.transaction() as tx:
            tx.add(
                ModuleReleaseRow(
                    id=release,
                    artifact_key="files",
                    source_commit=uuid4().hex + "a" * 8,
                    input_fingerprint=uuid4().hex + uuid4().hex,
                    platform="linux/amd64",
                    state="published",
                    image_reference="registry.example/files@sha256:" + "c" * 64,
                    storage_compatibility="workspace",
                )
            )
        update = self.command(
            action="modules",
            module=ModuleCommand(
                action="update",
                update=PlacementUpdate(
                    id=command.module.placement.id, release_uuid=release, expected_sequence=1
                ),
            ),
        )
        await self.place(update)
        self.assertEqual(self.spec.id, before.id)
        self.assertEqual(self.spec.workspace, before.workspace)
        self.assertEqual(self.spec.limits, before.limits)
        self.assertEqual(self.spec.project_uuid, before.project_uuid)
        self.assertNotEqual(self.spec.release.image, before.release.image)
        calls = len(self.calls)
        await self.place(update)
        self.assertEqual(len(self.calls), calls)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeModuleRow, before.id)
            assert row is not None
            self.assertEqual(row.sequence, 2)
            self.assertEqual(row.applied_release_uuid, release)
        stale = self.command(action="modules", module=update.module)
        with self.assertRaises(HTTPException) as denied:
            await self.place(stale)
        self.assertEqual(denied.exception.status_code, 409)

    async def test_disabled_node_denies_before_workspaces_or_remote_effects(self) -> None:
        async with self.db.transaction() as tx:
            node = await tx.get(NodeRow, self.node)
            assert node is not None
            node.enabled = False
        with self.assertRaises(HTTPException) as denied:
            await self.place(self.intent())
        self.assertEqual(denied.exception.status_code, 409)
        self.assertEqual(self.calls, [])

    async def test_update_never_adopts_another_module_private_storage(self) -> None:
        command = self.intent()
        assert command.module is not None and command.module.placement is not None
        await self.place(command)
        release = uuid4()
        async with self.db.transaction() as tx:
            placement = await tx.get(NodeModuleRow, command.module.placement.id)
            assert placement is not None
            storage = await tx.get(NodeStorageRow, placement.storage_uuid)
            assert storage is not None
            # Corrupt only this disposable fixture: an update must not turn a
            # browser/private cache into Files/Git-visible project storage.
            storage.purpose = "browser"
            tx.add(
                ModuleReleaseRow(
                    id=release,
                    artifact_key="files",
                    source_commit=uuid4().hex + "a" * 8,
                    input_fingerprint=uuid4().hex + uuid4().hex,
                    platform="linux/amd64",
                    state="published",
                    image_reference="registry.example/files@sha256:" + "d" * 64,
                    storage_compatibility="workspace",
                )
            )
        calls = len(self.calls)
        update = self.command(
            action="modules",
            module=ModuleCommand(
                action="update",
                update=PlacementUpdate(
                    id=command.module.placement.id, release_uuid=release, expected_sequence=1
                ),
            ),
        )
        with self.assertRaises(HTTPException) as denied:
            await self.place(update)
        self.assertEqual(denied.exception.status_code, 409)
        self.assertEqual(len(self.calls), calls)
        async with self.db.transaction() as tx:
            placement = await tx.get(NodeModuleRow, command.module.placement.id)
            assert placement is not None
            self.assertEqual(placement.sequence, 1)
            self.assertEqual(placement.applied_release_uuid, self.release)
