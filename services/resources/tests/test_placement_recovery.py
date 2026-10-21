"""Fresh runtime observation is necessary but never replaces owner/storage/image checks."""
import copy
import unittest
from contextlib import asynccontextmanager
from datetime import UTC,datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from node_protocol import Deployment,ModuleRelease,ResourceLimits,WorkspaceMount
from projects.module_placements import PlacementManager
from projects.placement_recovery import current_spec,verified_restoration
from projects._node_persistence import ModuleReleaseRow,NodeModuleRow,NodeOperationRow,NodeRow


class PlacementRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old=Deployment(id=uuid4(),node_uuid=uuid4(),project_uuid=uuid4(),workspace=WorkspaceMount(id=uuid4()),
            release=ModuleRelease(module="svc",image="registry.example/svc@sha256:"+"a"*64,lifecycle="sessionful"),
            limits=ResourceLimits(memory_bytes=1024**3,cpu_millis=500,pids=128))
        self.new=self.old.model_copy(update={"limits":self.old.limits.model_copy(update={"cpu_millis":600})})
        self.row=SimpleNamespace(id=uuid4(),node_uuid=self.old.node_uuid,placement_uuid=self.old.id,
            actor_uuid=uuid4(),sequence=2,phase="checking",error_code=None,previous=self.old.model_dump(mode="json"),
            desired=self.new.model_dump(mode="json"),updated_at=datetime.now(UTC))
        self.placement=SimpleNamespace(id=self.old.id,node_uuid=self.old.node_uuid,project_uuid=self.old.project_uuid,
            artifact_key="svc",storage_uuid=self.old.workspace.id,sequence=2,state="updating",
            applied_release_uuid=uuid4(),desired_release_uuid=uuid4(),limits=self.new.limits.model_dump(mode="json"))
        self.release=SimpleNamespace(image_reference=self.old.release.image,artifact_key="svc")
        self.receipt={"operation_uuid":str(self.row.id),"sequence":2,"phase":"failed","error":"UPDATE_FAILED"}
        self.inventory={"node_uuid":str(self.old.node_uuid),"enabled":True,"sequence":7,"items":[{
            "placement_uuid":str(self.old.id),"fingerprint":self.old.fingerprint,"running":True,"ready":True,
            "limits":self.old.limits.model_dump(mode="json")}]}
        self.audit=[]
        self.node=SimpleNamespace(id=self.old.node_uuid,sequence=7,deleted_at=None,enabled=True,public_key="pinned-node-test-key",endpoint="https://node.example")
        owner=self
        class Transaction:
            async def scalar(self,query):return owner.row
            async def get(self,model,key):return {NodeModuleRow:owner.placement,ModuleReleaseRow:owner.release,NodeOperationRow:owner.row,NodeRow:owner.node}.get(model)
            def add(self,record):owner.audit.append(record)
        class Database:
            @asynccontextmanager
            async def transaction(self):yield Transaction()
        self.manager=PlacementManager(lambda:Database(),None)

    async def save(self,inventory):
        with patch('projects.module_placements.operation_diagnostic',AsyncMock(return_value=None)):
            return await self.manager.save(self.row.id,self.receipt,inventory=inventory)

    async def test_verified_previous_becomes_ready_but_failed_update_is_preserved(self):
        self.assertTrue(await self.save(self.inventory))
        self.assertEqual((self.row.phase,self.row.error_code),("failed","UPDATE_FAILED"))
        self.assertEqual(self.placement.state,"ready")
        self.assertEqual(self.placement.limits,self.old.limits.model_dump(mode="json"))
        self.assertEqual(current_spec(self.placement,self.row),self.old)
        self.assertEqual(self.audit[0].details["restored_fingerprint"],self.old.fingerprint)

    async def test_failed_receipt_without_inventory_stays_closed_then_explicit_reconciliation_can_recover(self):
        await self.save(None)
        self.assertEqual(self.placement.state,"failed")
        await self.save(self.inventory)
        self.assertEqual(self.placement.state,"ready")

    async def test_mismatched_applied_image_cannot_restore(self):
        self.release.image_reference="registry.example/svc@sha256:"+"b"*64
        await self.save(self.inventory)
        self.assertEqual(self.placement.state,"failed")

    def test_wrong_node_ambiguous_unready_wrong_fingerprint_and_limits_are_rejected(self):
        for change in ('node','sequence','disabled','duplicate','unready','fingerprint','limits'):
            value=copy.deepcopy(self.inventory)
            if change=='node':value['node_uuid']=str(uuid4())
            elif change=='sequence':value['sequence']=6
            elif change=='disabled':value['enabled']=False
            elif change=='duplicate':value['items'].append(copy.deepcopy(value['items'][0]))
            elif change=='unready':value['items'][0]['ready']=False
            elif change=='fingerprint':value['items'][0]['fingerprint']=self.new.fingerprint
            else:value['items'][0]['limits']['cpu_millis']=600
            with self.subTest(change=change):
                self.assertIsNone(verified_restoration(self.placement,self.row,self.receipt,value,node=self.node))
        self.placement.storage_uuid=uuid4()
        self.assertIsNone(verified_restoration(self.placement,self.row,self.receipt,self.inventory,node=self.node))

    async def test_stale_operation_or_changed_terminal_receipt_never_changes_projection(self):
        self.placement.sequence=3
        with self.assertRaises(ValueError):await self.save(self.inventory)
        self.assertEqual(self.placement.state,"updating")
        self.placement.sequence=2;self.row.phase="failed";self.row.error_code="ROLLBACK_FAILED"
        with self.assertRaises(ValueError):await self.save(self.inventory)
        self.assertEqual(self.placement.state,"updating")

    async def test_terminal_reconcile_fetches_new_inventory_after_failed_receipt_without_apply(self):
        self.row.phase="failed";self.row.error_code="UPDATE_FAILED";self.placement.state="failed"
        calls=[]
        async def remote(**options):
            calls.append(options.get("action","inventory"))
            if options.get("action")=="status":return self.receipt
            return {**self.inventory,"event_cursor":0}
        self.manager.remote=SimpleNamespace(call=remote)
        self.manager.authorize=AsyncMock()
        with patch('projects.module_placements.operation_diagnostic',AsyncMock(return_value=None)):
            await self.manager.run(SimpleNamespace(project_uuid=self.old.project_uuid),self.row.id,False)
        self.assertEqual(calls,["inventory","status","inventory"])
        self.assertEqual(self.placement.state,"ready")
