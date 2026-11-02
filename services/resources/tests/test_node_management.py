"""Explicit disposable-Postgres acceptance; never targets the working database."""

import os
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.routing import APIRoute
from node_control_fixture import ControlCall, ControlFixture
from projects._node_persistence import (
    ModuleArtifactRow,
    ModuleReleaseRow,
    NodeModuleRow,
    NodeOperationRow,
    NodeRow,
    NodeStorageRow,
    ProjectModuleBindingRow,
)
from projects.infrastructure.catalog_records import InputPayload, artifact_definition
from projects.infrastructure.node_storage_models import (
    ArtifactConfigurationContract,
    ArtifactStorageContract,
    PlacementCreationMetadata,
)
from projects.node_management import (
    NodeCommand,
    NodeManagementBoundary,
    NodeRegistration,
    node_router,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from node_protocol import ResourceLimits
from node_protocol.catalog import ARTIFACTS
from node_protocol.domain.observations import NodeConfiguration, NodeInventory, NodeReply
from runtime_peer import PeerClient, VerifiedOwnerReply


@unittest.skipUnless(
    os.environ.get("NODE_SCHEMA_ACCEPTANCE") == "1",
    "Requires an explicitly provisioned disposable PostgreSQL",
)
class NodeManagementFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = OwnerDatabaseSettings(owner="resources")
        if settings.postgres_host != "briareus-node-schema-audit":
            raise RuntimeError("Refusing any non-disposable database")
        self.db = PlatformDatabase(settings)
        self.addAsyncCleanup(self.db.close)
        self.actor, self.project = uuid4(), uuid4()
        self.role = "operator"
        self.owner_team = uuid4()

        owner = self

        class Platform(PeerClient):
            def __init__(self) -> None:
                pass

            async def call[ReplyT](
                self,
                path: str,
                request: dict[str, object],
                *,
                decode: Callable[[int, object], ReplyT],
            ) -> VerifiedOwnerReply[ReplyT]:
                owner.assertEqual(path, "/internal/v1/platform/oidc/actor-context")
                return VerifiedOwnerReply(
                    200,
                    decode(
                        200,
                        {
                            "issuer": request["issuer"],
                            "subject": request["subject"],
                            "actor_uuid": str(owner.actor),
                            "project_uuid": str(owner.project),
                            "role": owner.role,
                            "permissions": ["use_resources"],
                            "project_owner_kind": "team",
                            "project_owner_uuid": str(owner.owner_team),
                            "expires_at": (datetime.now(UTC) + timedelta(seconds=15)).isoformat(),
                        },
                    ),
                )

        peer = Platform()
        router = node_router(
            platform=peer, resolve_database=lambda: self.db, cipher=Fernet(Fernet.generate_key())
        )
        self.router = router
        self.addAsyncCleanup(router.node_placements.close)
        route = router.routes[0]
        assert isinstance(route, APIRoute)
        boundary: object = getattr(route.endpoint, "__self__", None)
        assert isinstance(boundary, NodeManagementBoundary)
        self.endpoint = boundary.nodes
        self.request = Request(
            {"type": "http", "briareus.service_peer": "briareus:control-panel-api"}
        )

    async def asyncTearDown(self) -> None:
        await self.router.node_placements.close()
        await self.db.close()

    def command(self, **data: object) -> NodeCommand:
        return NodeCommand.model_validate(
            {
                "issuer": "https://provider.example",
                "subject": "real-test-fixture",
                "actor_uuid": self.actor,
                "project_uuid": self.project,
                "operation_uuid": uuid4(),
                "identity_expires_at": datetime.now(UTC) + timedelta(seconds=15),
                **data,
            }
        )

    def registration(self) -> NodeRegistration:
        return NodeRegistration.model_validate(
            {
                "id": str(uuid4()),
                "name": "Test node",
                "scope": "shared",
                "owner_uuid": None,
                "host_uuid": str(uuid4()),
                "runtime_uid": 2301,
                "endpoint": "https://node.example",
                "budget": {
                    "total": {"memory_bytes": 536870912, "cpu_millis": 1000, "pids": 256},
                    "reserved": {"memory_bytes": 134217728, "cpu_millis": 100, "pids": 32},
                },
            }
        )


class NodeManagementTests(NodeManagementFixture):
    async def test_registration_is_disabled_and_operation_is_idempotent(self) -> None:
        value = self.registration()
        command = self.command(action="register", registration=value)
        assert command.registration is not None
        first = await self.endpoint(command, self.request)
        again = await self.endpoint(command, self.request)
        self.assertEqual(first.body, again.body)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, command.registration.id)
            assert row is not None
            self.assertFalse(row.enabled)
            self.assertEqual(row.sequence, 1)
            count = await tx.scalar(
                select(func.count()).select_from(NodeRow).where(NodeRow.id == row.id)
            )
            self.assertEqual(count, 1)

    async def test_team_owner_must_be_verified_and_nonoperator_denied(self) -> None:
        value = {**self.registration().model_dump(), "scope": "team", "owner_uuid": str(uuid4())}
        with self.assertRaises(HTTPException) as denied:
            await self.endpoint(self.command(action="register", registration=value), self.request)
        self.assertEqual(denied.exception.status_code, 403)
        self.role = "user"
        with self.assertRaises(HTTPException) as denied:
            await self.endpoint(self.command(action="list"), self.request)
        self.assertEqual(denied.exception.status_code, 403)

    async def test_rename_checks_sequence_and_rejects_operation_reuse(self) -> None:
        command = self.command(action="register", registration=self.registration())
        assert command.registration is not None
        await self.endpoint(command, self.request)
        renamed = self.command(
            action="rename", node_uuid=command.registration.id, name="Renamed", expected_sequence=1
        )
        await self.endpoint(renamed, self.request)
        with self.assertRaises(HTTPException) as conflict:
            await self.endpoint(renamed.model_copy(update={"name": "Different"}), self.request)
        self.assertEqual(conflict.exception.status_code, 409)
        with self.assertRaises(HTTPException) as conflict:
            await self.endpoint(
                self.command(
                    action="disable", node_uuid=command.registration.id, expected_sequence=1
                ),
                self.request,
            )
        self.assertEqual(conflict.exception.status_code, 409)

    async def test_database_rejects_cross_node_storage_attachment(self) -> None:
        first = self.command(action="register", registration=self.registration())
        second = self.command(action="register", registration=self.registration())
        assert first.registration is not None and second.registration is not None
        await self.endpoint(first, self.request)
        await self.endpoint(second, self.request)
        with self.assertRaises(IntegrityError):
            async with self.db.transaction() as tx:
                artifact = ModuleArtifactRow(
                    key="isolated-" + uuid4().hex[:16],
                    name="Test artifact",
                    inputs=InputPayload.from_record(artifact_definition(ARTIFACTS["files"]).inputs),
                    configuration_contract=ArtifactConfigurationContract(
                        kind="approved_node_adapter"
                    ),
                    storage_contract=ArtifactStorageContract(workspace=True, purpose="workspace"),
                    enabled=False,
                )
                tx.add(artifact)
                await tx.flush()
                storage = NodeStorageRow(
                    id=uuid4(),
                    node_uuid=first.registration.id,
                    project_uuid=self.project,
                    purpose="workspace",
                    quota_bytes=1024,
                    retention="persistent",
                )
                tx.add(storage)
                await tx.flush()
                tx.add(
                    NodeModuleRow(
                        node_uuid=second.registration.id,
                        project_uuid=self.project,
                        artifact_key=artifact.key,
                        name="Wrong node",
                        storage_uuid=storage.id,
                        limits=ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=100, pids=32),
                    )
                )
                await tx.flush()

    async def test_pair_enable_and_receipt_replay(self) -> None:
        registered = self.command(action="register", registration=self.registration())
        assert registered.registration is not None
        await self.endpoint(registered, self.request)
        public = (
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )

        def respond(call: ControlCall) -> NodeReply:
            if call.action == "inventory":
                return NodeInventory(call.node_uuid, False, 0, call.sequence, ())
            return NodeConfiguration(call.node_uuid, call.sequence, call.action == "configure")

        remote = ControlFixture(respond)
        self.addAsyncCleanup(remote.close)
        calls = remote.calls
        with patch("projects.node_control.NodeControl.from_environment", return_value=remote):
            paired = self.command(
                action="pair",
                node_uuid=registered.registration.id,
                expected_sequence=1,
                public_key=public,
            )
            first = await self.endpoint(paired, self.request)
            self.assertEqual((await self.endpoint(paired, self.request)).body, first.body)
            self.assertEqual(len(calls), 1)
            enabled = self.command(
                action="enable", node_uuid=registered.registration.id, expected_sequence=2
            )
            await self.endpoint(enabled, self.request)
            await self.endpoint(enabled, self.request)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[-1].sequence, 3)
            assert calls[-1].record is not None
            self.assertTrue(calls[-1].record.enabled)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, registered.registration.id)
            assert row is not None
            self.assertTrue(row.enabled)
            self.assertEqual(row.public_key, public)
            self.assertEqual(row.sequence, 3)

    async def test_revoked_operator_cannot_commit_remote_pairing(self) -> None:
        registered = self.command(action="register", registration=self.registration())
        assert registered.registration is not None
        await self.endpoint(registered, self.request)
        public = (
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )

        def respond(call: ControlCall) -> NodeReply:
            self.role = "user"
            return NodeInventory(call.node_uuid, False, 0, 0, ())

        remote = ControlFixture(respond)
        self.addAsyncCleanup(remote.close)
        with patch("projects.node_control.NodeControl.from_environment", return_value=remote):
            with self.assertRaises(HTTPException) as denied:
                await self.endpoint(
                    self.command(
                        action="pair",
                        node_uuid=registered.registration.id,
                        expected_sequence=1,
                        public_key=public,
                    ),
                    self.request,
                )
            self.assertEqual(denied.exception.status_code, 403)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, registered.registration.id)
            assert row is not None
            self.assertIsNone(row.public_key)
            self.assertFalse(row.enabled)
            self.assertEqual(row.sequence, 1)

    async def test_budget_requires_remote_confirmation_and_replay_preserves_sequence(self) -> None:
        import json

        from projects.node_control import NodeUnavailable

        from node_protocol import NodeBudget, ResourceLimits

        registered = self.command(action="register", registration=self.registration())
        assert registered.registration is not None
        await self.endpoint(registered, self.request)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, registered.registration.id)
            assert row is not None
            row.public_key = "pinned-fixture"
            row.enabled = True
        value = NodeBudget(
            total=ResourceLimits(memory_bytes=2048 * 1024**2, cpu_millis=2000, pids=512),
            reserved=ResourceLimits(memory_bytes=384 * 1024**2, cpu_millis=750, pids=192),
        )
        command = self.command(
            action="budget", node_uuid=registered.registration.id, expected_sequence=1, budget=value
        )

        def respond(call: ControlCall) -> NodeReply:
            if len(remote.calls) == 1:
                raise NodeUnavailable("Provisioned ceiling rejected")
            assert call.record is not None
            return NodeConfiguration(call.node_uuid, call.sequence, call.record.enabled)

        remote = ControlFixture(respond)
        self.addAsyncCleanup(remote.close)
        calls = remote.calls
        with patch("projects.node_control.NodeControl.from_environment", return_value=remote):
            with self.assertRaises(HTTPException) as denied:
                await self.endpoint(command, self.request)
            self.assertEqual(denied.exception.status_code, 503)
            async with self.db.transaction() as tx:
                row = await tx.get(NodeRow, command.node_uuid)
                assert row is not None
                self.assertEqual(row.sequence, 1)
            response = await self.endpoint(command, self.request)
            self.assertEqual(json.loads(bytes(response.body))["item"]["budget"], value.model_dump())
            self.assertEqual((await self.endpoint(command, self.request)).body, response.body)
            self.assertEqual(len(calls), 2)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, command.node_uuid)
            assert row is not None
            self.assertEqual(row.sequence, 2)
            self.assertTrue(row.enabled)

    async def test_route_requires_published_applied_project_binding_and_enabled_node(self) -> None:
        import json

        from projects.node_routing import RouteQuery, route_router

        from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount

        registered = self.command(action="register", registration=self.registration())
        assert registered.registration is not None
        await self.endpoint(registered, self.request)
        key = Ed25519PrivateKey.generate()
        spec = Deployment(
            id=uuid4(),
            node_uuid=registered.registration.id,
            project_uuid=self.project,
            workspace=WorkspaceMount(id=uuid4()),
            effect_verify_key=key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
            release=ModuleRelease(
                module="files",
                image="registry.example/files@sha256:" + "d" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=100, pids=32),
        )
        release_id = uuid4()
        assert spec.workspace is not None
        async with self.db.transaction() as tx:
            node = await tx.get(NodeRow, registered.registration.id)
            assert node is not None
            node.enabled = True
            node.public_key = "prior-verified-enrollment-fixture"
            if await tx.get(ModuleArtifactRow, "files") is None:
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
            tx.add(
                ModuleReleaseRow(
                    id=release_id,
                    artifact_key="files",
                    source_commit=uuid4().hex + "a" * 8,
                    platform="linux/amd64",
                    input_fingerprint=uuid4().hex + uuid4().hex,
                    image_reference=spec.release.image,
                    state="published",
                    storage_compatibility="workspace",
                )
            )
            await tx.flush()
            tx.add(
                NodeStorageRow(
                    id=spec.workspace.id,
                    node_uuid=spec.node_uuid,
                    project_uuid=self.project,
                    purpose="workspace",
                    quota_bytes=1024**3,
                    retention="persistent",
                )
            )
            await tx.flush()
            tx.add(
                NodeModuleRow(
                    id=spec.id,
                    node_uuid=spec.node_uuid,
                    project_uuid=self.project,
                    artifact_key="files",
                    name="Project files",
                    desired_release_uuid=release_id,
                    applied_release_uuid=release_id,
                    storage_uuid=spec.workspace.id,
                    configuration=PlacementCreationMetadata(),
                    limits=spec.limits,
                    state="ready",
                )
            )
            await tx.flush()
            tx.add(
                ProjectModuleBindingRow(
                    project_uuid=self.project, placement_uuid=spec.id, logical_key="files"
                )
            )
            tx.add(
                NodeOperationRow(
                    node_uuid=spec.node_uuid,
                    placement_uuid=spec.id,
                    actor_uuid=self.actor,
                    sequence=1,
                    fingerprint=spec.fingerprint,
                    desired=spec,
                    phase="succeeded",
                )
            )
        route_entry = route_router(lambda: self.db).routes[0]
        assert isinstance(route_entry, APIRoute)
        route = route_entry.endpoint
        query = RouteQuery(project_uuid=self.project, module="files")
        gateway = Request({"type": "http", "briareus.service_peer": "briareus:gateway"})
        with patch.dict(os.environ, {"BRIAREUS_NODE_ORIGINS": '["https://node.example"]'}):
            result = json.loads((await route(query, gateway)).body)["route"]
            self.assertEqual(result["fingerprint"], spec.fingerprint)
            self.assertEqual(result["placement_uuid"], str(spec.id))
            authority = Request(
                {
                    "type": "http",
                    "path": "/internal/v1/resources/node-files-authority",
                    "briareus.service_peer": "briareus:authorization",
                }
            )
            binding = json.loads((await route(query, authority)).body)["binding"]
            self.assertEqual(binding["workspace_uuid"], str(spec.workspace.id))
            self.assertEqual(binding["effect_verify_key"], spec.effect_verify_key)
            with self.assertRaises(HTTPException) as denied:
                await route(query, self.request)
            self.assertEqual(denied.exception.status_code, 403)
            with self.assertRaises(HTTPException) as denied:
                await route(RouteQuery(project_uuid=uuid4(), module="files"), gateway)
            self.assertEqual(denied.exception.status_code, 503)
            async with self.db.transaction() as tx:
                node = await tx.get(NodeRow, spec.node_uuid)
                assert node is not None
                node.enabled = False
            with self.assertRaises(HTTPException) as denied:
                await route(query, gateway)
            self.assertEqual(denied.exception.status_code, 503)
