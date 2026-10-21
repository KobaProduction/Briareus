"""Owner-attested node workspace scopes; no node identity can grant permissions."""
import time
import unittest
from uuid import uuid4

from node_protocol.files import workspace_resource
from authorization._runtime_resource_owners import CurrentRuntimeResourceOwners


class NodeResourceOwnersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.project,self.node,self.workspace=uuid4(),uuid4(),uuid4()
        self.binding=dict(node_uuid=str(self.node),placement_uuid=str(uuid4()),project_uuid=str(self.project),
            workspace_uuid=str(self.workspace),fingerprint="a"*64,resource_revision=7,
            resource_id=workspace_resource(self.node,self.project,self.workspace),
            effect_verify_key="public-key-fixture"*6,expires_at=int(time.time())+5)
        self.scope=dict(hand="files",tool="file_list",action="files.read",
            resource=dict(kind="workspace_path",id=self.binding["resource_id"]))

    def peer(self, module="files"):
        owner=self
        class Peer:
            async def call(self,path,body):
                owner.assertEqual(path,"/internal/v1/resources/node-"+module+"-authority")
                owner.assertEqual(body,{"project_uuid":str(owner.project),"module":module})
                return 200,{"binding":owner.binding}
        return Peer()

    async def test_exact_workspace_and_actual_owner_sequence_are_required(self):
        owners=await CurrentRuntimeResourceOwners.inspect_owners({},self.project,[self.scope],node_resources=self.peer())
        proof=owners.verify_current_scope(project_uuid=self.project,scope=self.scope)
        self.assertEqual(proof.revision,7)
        self.assertEqual(proof.resource.id,self.binding["resource_id"])
        self.assertIsNone(owners.verify_current_scope(project_uuid=uuid4(),scope=self.scope))
        wrong={**self.scope,"resource":{**self.scope["resource"],"id":workspace_resource(self.node,self.project,uuid4())}}
        with self.assertRaises(ValueError):
            await CurrentRuntimeResourceOwners.inspect_owners({},self.project,[wrong],node_resources=self.peer())

    async def test_stale_other_project_and_unbound_owner_projections_fail_closed(self):
        original=dict(self.binding)
        for fields in [{"expires_at":int(time.time())-1},{"project_uuid":str(uuid4())},
                       {"resource_id":workspace_resource(self.node,self.project,uuid4())},{"resource_revision":0}]:
            self.binding={**original,**fields}
            with self.assertRaises(ValueError):
                await CurrentRuntimeResourceOwners.node_files(self.peer(),self.project)

    async def test_terminal_uses_its_own_module_and_workspace_selector(self):
        from node_protocol.terminal import workspace_resource as terminal_resource
        self.binding["resource_id"] = terminal_resource(self.node,self.project,self.workspace)
        scope = dict(hand="terminal",tool="terminal_exec",action="terminal.execute",
            resource=dict(kind="workspace",id=self.binding["resource_id"]))
        owners = await CurrentRuntimeResourceOwners.inspect_owners({},self.project,[scope],
            node_resources=self.peer("terminal"))
        proof = owners.verify_current_scope(project_uuid=self.project,scope=scope)
        self.assertEqual(proof.revision,7)
        self.assertEqual(proof.hand,"terminal")
        self.binding["resource_id"] = workspace_resource(self.node,self.project,self.workspace)
        with self.assertRaises(ValueError):
            await CurrentRuntimeResourceOwners.inspect_owners({},self.project,[scope],
                node_resources=self.peer("terminal"))

    async def test_all_module_resources_need_their_own_current_binding(self):
        from node_protocol.module_effects import MODULES, RESOURCE_KINDS, effect_action, resource_id
        selected = {"files": "file_read", "terminal": "terminal_exec", "web": "browser_open",
            "svc": "github_accounts", "infrastructure": "observability_sources", "reverse": "list_projects",
            "serena": "get_symbols_overview"}
        for module in sorted(MODULES):
            with self.subTest(module=module):
                self.binding["resource_id"] = resource_id(module, self.node, self.project, self.workspace)
                tool = selected[module]
                scope = dict(hand=module, tool=tool, action=effect_action(module, tool),
                    resource=dict(kind=RESOURCE_KINDS[module], id=self.binding["resource_id"]))
                owners = await CurrentRuntimeResourceOwners.inspect_owners({}, self.project, [scope],
                    node_resources=self.peer(module))
                proof = owners.verify_current_scope(project_uuid=self.project, scope=scope)
                self.assertEqual((proof.hand, proof.tool, proof.revision), (module, tool, 7))
                self.binding["resource_id"] = resource_id(module, self.node, self.project, uuid4())
                with self.assertRaises(ValueError):
                    await CurrentRuntimeResourceOwners.inspect_owners({}, self.project, [scope],
                        node_resources=self.peer(module))

    async def test_missing_node_owner_never_borrows_a_legacy_owner(self):
        class LegacyOwner:
            async def call(self, *_):
                raise AssertionError("Legacy owner must not substitute Node evidence")
        with self.assertRaises(ValueError):
            await CurrentRuntimeResourceOwners.inspect_owners({"files": LegacyOwner()}, self.project, [self.scope])

    async def test_new_hand_request_models_and_reserved_project_names_are_exact(self):
        from authorization._decision_api import DecisionCommand
        from authorization._rauthy_access_commands import ScopeEffect
        from authorization._resource_scope import validate_project_resource_scope, EffectResource
        from node_protocol.module_effects import RESOURCE_KINDS, effect_action, resource_id
        for module, tool in (("reverse", "radare2_binary_info"), ("serena", "get_symbols_overview")):
            resource = EffectResource(kind=RESOURCE_KINDS[module],
                id=resource_id(module, self.node, self.project, self.workspace))
            ScopeEffect(hand=module, tool=tool, action=effect_action(module, tool), resource=resource.model_dump())
            DecisionCommand(project_uuid=self.project, agent_session_uuid=uuid4(), expected_grant_revision=1,
                action=effect_action(module, tool), hand=module, tool=tool, resource=resource)
            with self.assertRaises(ValueError):
                validate_project_resource_scope(project_uuid=uuid4(), hand=module, tool=tool, resource=resource)
            with self.assertRaises(ValueError):
                DecisionCommand(project_uuid=self.project, agent_session_uuid=uuid4(), expected_grant_revision=1,
                    action="files.read", hand=module, tool=tool, resource=resource)
