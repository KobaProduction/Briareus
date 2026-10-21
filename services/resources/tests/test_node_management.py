"""Explicit disposable-Postgres acceptance; never targets the working database."""
import os
import unittest
from unittest.mock import patch
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from projects._node_persistence import NodeRow, NodeStorageRow, NodeModuleRow, ModuleArtifactRow
from projects._node_persistence import ModuleReleaseRow, NodeOperationRow, ProjectModuleBindingRow
from projects.node_management import NodeCommand, node_router


@unittest.skipUnless(os.environ.get("NODE_SCHEMA_ACCEPTANCE") == "1",
                     "Requires an explicitly provisioned disposable PostgreSQL")
class NodeManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings = OwnerDatabaseSettings(owner="resources")
        if settings.postgres_host != "briareus-node-schema-audit":
            raise RuntimeError("Refusing any non-disposable database")
        self.db = PlatformDatabase(settings)
        self.actor, self.project = uuid4(), uuid4()
        self.role = "operator"
        self.owner_team = uuid4()

        async def call(path, request):
            return 200, {"issuer": request["issuer"], "subject": request["subject"],
                "actor_uuid": str(self.actor), "project_uuid": str(self.project),
                "role": self.role, "permissions": ["use_resources"],
                "project_owner_kind": "team", "project_owner_uuid": str(self.owner_team),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=15)).isoformat()}
        peer = type("Platform", (), {"call": staticmethod(call)})()
        router = node_router(platform=peer, resolve_database=lambda: self.db, cipher=Fernet(Fernet.generate_key()))
        self.router=router
        self.endpoint = router.routes[0].endpoint
        self.request = Request({"type": "http", "briareus.service_peer": "briareus:control-panel-api"})

    async def asyncTearDown(self):
        await self.router.node_placements.close()
        await self.db.close()

    def command(self, **data):
        return NodeCommand(issuer="https://provider.example", subject="real-test-fixture",
            actor_uuid=self.actor, project_uuid=self.project, operation_uuid=uuid4(),
            identity_expires_at=datetime.now(UTC) + timedelta(seconds=15), **data)

    def registration(self):
        return {"id": str(uuid4()), "name": "Test node", "scope": "shared", "owner_uuid": None,
                "host_uuid": str(uuid4()), "runtime_uid": 2301, "endpoint": "https://node.example",
                "budget": {"total": {"memory_bytes": 536870912, "cpu_millis": 1000, "pids": 256},
                           "reserved": {"memory_bytes": 134217728, "cpu_millis": 100, "pids": 32}}}

    async def test_registration_is_disabled_and_operation_is_idempotent(self):
        value = self.registration()
        command = self.command(action="register", registration=value)
        first = await self.endpoint(command, self.request)
        again = await self.endpoint(command, self.request)
        self.assertEqual(first.body, again.body)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, command.registration.id)
            self.assertFalse(row.enabled)
            self.assertEqual(row.sequence, 1)
            count = await tx.scalar(select(func.count()).select_from(NodeRow).where(NodeRow.id == row.id))
            self.assertEqual(count, 1)

    async def test_team_owner_must_be_verified_and_nonoperator_denied(self):
        value = {**self.registration(), "scope": "team", "owner_uuid": str(uuid4())}
        with self.assertRaises(HTTPException) as denied:
            await self.endpoint(self.command(action="register", registration=value), self.request)
        self.assertEqual(denied.exception.status_code, 403)
        self.role = "user"
        with self.assertRaises(HTTPException) as denied:
            await self.endpoint(self.command(action="list"), self.request)
        self.assertEqual(denied.exception.status_code, 403)

    async def test_rename_checks_sequence_and_rejects_operation_reuse(self):
        command = self.command(action="register", registration=self.registration())
        await self.endpoint(command, self.request)
        renamed = self.command(action="rename", node_uuid=command.registration.id, name="Renamed", expected_sequence=1)
        await self.endpoint(renamed, self.request)
        with self.assertRaises(HTTPException) as conflict:
            await self.endpoint(renamed.model_copy(update={"name": "Different"}), self.request)
        self.assertEqual(conflict.exception.status_code, 409)
        with self.assertRaises(HTTPException) as conflict:
            await self.endpoint(self.command(action="disable", node_uuid=command.registration.id,
                                            expected_sequence=1), self.request)
        self.assertEqual(conflict.exception.status_code, 409)

    async def test_database_rejects_cross_node_storage_attachment(self):
        first = self.command(action="register", registration=self.registration())
        second = self.command(action="register", registration=self.registration())
        await self.endpoint(first, self.request)
        await self.endpoint(second, self.request)
        with self.assertRaises(IntegrityError):
            async with self.db.transaction() as tx:
                artifact = ModuleArtifactRow(key="isolated-" + uuid4().hex[:16], name="Test artifact",
                    inputs={}, configuration_contract={}, storage_contract={}, enabled=False)
                tx.add(artifact)
                await tx.flush()
                storage = NodeStorageRow(id=uuid4(), node_uuid=first.registration.id,
                    project_uuid=self.project, purpose="workspace", quota_bytes=1024, retention="persistent")
                tx.add(storage)
                await tx.flush()
                tx.add(NodeModuleRow(node_uuid=second.registration.id, project_uuid=self.project,
                    artifact_key=artifact.key, name="Wrong node", storage_uuid=storage.id, limits={}))
                await tx.flush()

    async def test_pair_enable_and_receipt_replay(self):
        registered = self.command(action="register", registration=self.registration())
        await self.endpoint(registered, self.request)
        public = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        calls = []
        async def call(**kwargs):
            calls.append(kwargs)
            return {"node_uuid": str(kwargs["node_uuid"]),
                    "enabled": kwargs.get("action") == "configure", "sequence": kwargs["sequence"]}
        remote = type("Remote", (), {"call": staticmethod(call)})()
        with patch("projects.node_control.NodeControl.from_environment", return_value=remote):
            paired = self.command(action="pair", node_uuid=registered.registration.id,
                                  expected_sequence=1, public_key=public)
            first = await self.endpoint(paired, self.request)
            self.assertEqual((await self.endpoint(paired, self.request)).body, first.body)
            self.assertEqual(len(calls), 1)
            enabled = self.command(action="enable", node_uuid=registered.registration.id, expected_sequence=2)
            await self.endpoint(enabled, self.request)
            await self.endpoint(enabled, self.request)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[-1]["sequence"], 3)
            self.assertTrue(calls[-1]["record"].enabled)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, registered.registration.id)
            self.assertTrue(row.enabled)
            self.assertEqual(row.public_key, public)
            self.assertEqual(row.sequence, 3)

    async def test_revoked_operator_cannot_commit_remote_pairing(self):
        registered = self.command(action="register", registration=self.registration())
        await self.endpoint(registered, self.request)
        public = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        async def call(**kwargs):
            self.role = "user"
            return {"node_uuid": str(kwargs["node_uuid"]), "enabled": False, "sequence": 0}
        remote = type("Remote", (), {"call": staticmethod(call)})()
        with patch("projects.node_control.NodeControl.from_environment", return_value=remote):
            with self.assertRaises(HTTPException) as denied:
                await self.endpoint(self.command(action="pair", node_uuid=registered.registration.id,
                    expected_sequence=1, public_key=public), self.request)
            self.assertEqual(denied.exception.status_code, 403)
        async with self.db.transaction() as tx:
            row = await tx.get(NodeRow, registered.registration.id)
            self.assertIsNone(row.public_key)
            self.assertFalse(row.enabled)
            self.assertEqual(row.sequence,1)

    async def test_budget_requires_remote_confirmation_and_replay_preserves_sequence(self):
        import json
        from node_protocol import NodeBudget,ResourceLimits
        from projects.node_control import NodeUnavailable
        registered=self.command(action="register",registration=self.registration())
        await self.endpoint(registered,self.request)
        async with self.db.transaction() as tx:
            row=await tx.get(NodeRow,registered.registration.id)
            row.public_key="pinned-fixture"
            row.enabled=True
        value=NodeBudget(total=ResourceLimits(memory_bytes=2048*1024**2,cpu_millis=2000,pids=512),
            reserved=ResourceLimits(memory_bytes=384*1024**2,cpu_millis=750,pids=192))
        command=self.command(action="budget",node_uuid=registered.registration.id,expected_sequence=1,budget=value)
        calls=[]
        async def call(**kwargs):
            calls.append(kwargs)
            if len(calls)==1:
                raise NodeUnavailable("Provisioned ceiling rejected")
            return {"node_uuid":str(kwargs["node_uuid"]),"enabled":kwargs["record"].enabled,
                "sequence":kwargs["sequence"]}
        remote=type("Remote",(),{"call":staticmethod(call)})()
        with patch("projects.node_control.NodeControl.from_environment",return_value=remote):
            with self.assertRaises(HTTPException) as denied:
                await self.endpoint(command,self.request)
            self.assertEqual(denied.exception.status_code,503)
            async with self.db.transaction() as tx:
                self.assertEqual((await tx.get(NodeRow,command.node_uuid)).sequence,1)
            response=await self.endpoint(command,self.request)
            self.assertEqual(json.loads(response.body)["item"]["budget"],value.model_dump())
            self.assertEqual((await self.endpoint(command,self.request)).body,response.body)
            self.assertEqual(len(calls),2)
        async with self.db.transaction() as tx:
            row=await tx.get(NodeRow,command.node_uuid)
            self.assertEqual(row.sequence,2)
            self.assertTrue(row.enabled)

    async def test_route_requires_published_applied_project_binding_and_enabled_node(self):
        import json
        from node_protocol import Deployment, ModuleRelease, ResourceLimits, WorkspaceMount
        from projects.node_routing import route_router, RouteQuery
        registered = self.command(action="register", registration=self.registration())
        await self.endpoint(registered, self.request)
        key = Ed25519PrivateKey.generate()
        spec = Deployment(id=uuid4(), node_uuid=registered.registration.id, project_uuid=self.project,
            workspace=WorkspaceMount(id=uuid4()), effect_verify_key=key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
            release=ModuleRelease(module="files", image="registry.example/files@sha256:"+"d"*64,
                                  lifecycle="sessionful"),
            limits=ResourceLimits(memory_bytes=128*1024**2, cpu_millis=100, pids=32))
        release_id = uuid4()
        async with self.db.transaction() as tx:
            node = await tx.get(NodeRow, registered.registration.id)
            node.enabled = True
            node.public_key = "prior-verified-enrollment-fixture"
            if await tx.get(ModuleArtifactRow,"files") is None:
                tx.add(ModuleArtifactRow(key="files", name="Files", inputs={}, configuration_contract={},
                                         storage_contract={}, enabled=True))
            await tx.flush()
            tx.add(ModuleReleaseRow(id=release_id, artifact_key="files", source_commit="a"*40,
                platform="linux/amd64", input_fingerprint="b"*64, image_reference=spec.release.image,
                state="published", storage_compatibility="workspace"))
            await tx.flush()
            tx.add(NodeStorageRow(id=spec.workspace.id,node_uuid=spec.node_uuid,project_uuid=self.project,
                purpose="workspace",quota_bytes=1024**3,retention="persistent"))
            await tx.flush()
            tx.add(NodeModuleRow(id=spec.id, node_uuid=spec.node_uuid, project_uuid=self.project,
                artifact_key="files", name="Project files", desired_release_uuid=release_id,
                applied_release_uuid=release_id, storage_uuid=spec.workspace.id,
                configuration={}, limits=spec.limits.model_dump(), state="ready"))
            await tx.flush()
            tx.add(ProjectModuleBindingRow(project_uuid=self.project, placement_uuid=spec.id, logical_key="files"))
            tx.add(NodeOperationRow(node_uuid=spec.node_uuid, placement_uuid=spec.id, actor_uuid=self.actor,
                sequence=1, fingerprint=spec.fingerprint, desired=spec.model_dump(mode="json"), phase="succeeded"))
        route = route_router(lambda: self.db).routes[0].endpoint
        query = RouteQuery(project_uuid=self.project, module="files")
        gateway = Request({"type":"http", "briareus.service_peer":"briareus:gateway"})
        with patch.dict(os.environ, {"BRIAREUS_NODE_ORIGINS": '["https://node.example"]'}):
            result = json.loads((await route(query, gateway)).body)["route"]
            self.assertEqual(result["fingerprint"], spec.fingerprint)
            self.assertEqual(result["placement_uuid"], str(spec.id))
            authority=Request({"type":"http","path":"/internal/v1/resources/node-files-authority",
                "briareus.service_peer":"briareus:authorization"})
            binding=json.loads((await route(query,authority)).body)["binding"]
            self.assertEqual(binding["workspace_uuid"],str(spec.workspace.id))
            self.assertEqual(binding["effect_verify_key"],spec.effect_verify_key)
            with self.assertRaises(HTTPException) as denied:
                await route(query, self.request)
            self.assertEqual(denied.exception.status_code,403)
            with self.assertRaises(HTTPException) as denied:
                await route(RouteQuery(project_uuid=uuid4(), module="files"),gateway)
            self.assertEqual(denied.exception.status_code,503)
            async with self.db.transaction() as tx:
                node = await tx.get(NodeRow, spec.node_uuid)
                node.enabled = False
            with self.assertRaises(HTTPException) as denied:
                await route(query,gateway)
            self.assertEqual(denied.exception.status_code,503)
