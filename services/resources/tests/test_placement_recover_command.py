import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from node_protocol import Deployment, ModuleRelease, WorkspaceMount, ResourceLimits
from projects.module_placements import PlacementManager
from projects._node_persistence import NodeModuleRow,NodeOperationRow,NodeRow,NodeStorageRow,ModuleReleaseRow,ModuleArtifactRow

class RecoverCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_signed_intent_preserves_exact_spec_and_retry_never_redispatches(self):
        actor=uuid4();release_id=uuid4()
        spec=Deployment(id=uuid4(),node_uuid=uuid4(),project_uuid=uuid4(),workspace=WorkspaceMount(id=uuid4()),
            release=ModuleRelease(module="files",image="registry.example/files@sha256:"+"a"*64,lifecycle="stateless"),
            limits=ResourceLimits(memory_bytes=256*1024**2,cpu_millis=200,pids=64))
        placement=SimpleNamespace(id=spec.id,project_uuid=spec.project_uuid,node_uuid=spec.node_uuid,artifact_key="files",
            sequence=3,state="ready",applied_release_uuid=release_id,storage_uuid=spec.workspace.id)
        prior=SimpleNamespace(phase="succeeded",error_code=None,desired=spec.model_dump(mode="json"),previous=None)
        node=SimpleNamespace(id=spec.node_uuid,scope="personal",owner_uuid=actor,enabled=True,deleted_at=None,public_key="pinned")
        release=SimpleNamespace(id=release_id,state="published",artifact_key="files",image_reference=spec.release.image)
        storage=SimpleNamespace(id=spec.workspace.id,node_uuid=node.id,project_uuid=spec.project_uuid,retention="persistent")
        operations={};calls=[]
        class Tx:
            async def scalar(self,statement):
                return placement if "resources.node_modules" in str(statement) else prior
            async def get(self,model,key):
                return operations.get(key) if model is NodeOperationRow else {NodeRow:node,ModuleReleaseRow:release,ModuleArtifactRow:SimpleNamespace(enabled=True),NodeStorageRow:storage}.get(model)
            def add(self,row):operations[row.id]=row
            async def flush(self):pass
        class Database:
            @asynccontextmanager
            async def transaction(self):yield Tx()
        manager=PlacementManager(lambda:Database(),AsyncMock(return_value=({},datetime.now(UTC)+timedelta(seconds=30))))
        manager.start=Mock(side_effect=lambda command,operation,dispatch:calls.append(dispatch))
        manager.audit=Mock()
        command=SimpleNamespace(module=SimpleNamespace(recover=SimpleNamespace(id=spec.id,expected_sequence=3)),
            actor_uuid=actor,project_uuid=spec.project_uuid,operation_uuid=uuid4())
        with patch("projects.module_placements.operation_diagnostic",AsyncMock(return_value=None)),patch("projects.module_placements.operation_summary",return_value={"phase":"queued"}):
            await manager.recover(command,datetime.now(UTC)+timedelta(seconds=20))
            await manager.recover(command,datetime.now(UTC)+timedelta(seconds=20))
        saved=operations[command.operation_uuid]
        self.assertEqual(saved.desired,spec.model_dump(mode="json"))
        self.assertEqual(saved.previous,saved.desired)
        self.assertEqual(saved.fingerprint,spec.fingerprint)
        self.assertEqual(saved.sequence,4)
        self.assertEqual(calls,[True,False])
