"""Owner-attested node workspace scopes; no node identity can grant permissions."""

import time
import unittest
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from authorization._runtime_resource_owners import CurrentRuntimeResourceOwners
from authorization.domain.resource_scopes import HandName
from authorization.domain.sessions import SessionResourceGrant
from node_protocol.effect import NodeWorkspaceBinding, NodeWorkspaceReply
from node_protocol.files import workspace_resource
from runtime_peer import PeerClient, VerifiedOwnerReply


class BindingPeer(PeerClient):
    def __init__(self, target: "NodeResourceOwnersTests", module: str) -> None:
        self.target, self.module = target, module

    async def call[ReplyT](
        self, path: str, payload: dict[str, object], *, decode: Callable[[int, object], ReplyT]
    ) -> VerifiedOwnerReply[ReplyT]:
        self.target.assertEqual(path, "/internal/v1/resources/node-" + self.module + "-authority")
        self.target.assertEqual(
            payload, {"project_uuid": str(self.target.project), "module": self.module}
        )
        raw = NodeWorkspaceReply(binding=self.target.binding).model_dump(mode="json")
        return VerifiedOwnerReply(200, decode(200, raw))


class NodeResourceOwnersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project, self.node, self.workspace = uuid4(), uuid4(), uuid4()
        self.binding = NodeWorkspaceBinding(
            node_uuid=self.node,
            placement_uuid=uuid4(),
            project_uuid=self.project,
            workspace_uuid=self.workspace,
            fingerprint="a" * 64,
            resource_revision=7,
            resource_id=workspace_resource(self.node, self.project, self.workspace),
            effect_verify_key="public-key-fixture" * 6,
            expires_at=int(time.time()) + 5,
        )
        self.scope = SessionResourceGrant(
            "files", "file_list", "files.read", "workspace_path", self.binding.resource_id
        )

    def peer(self, module: str = "files") -> BindingPeer:
        return BindingPeer(self, module)

    async def test_exact_workspace_and_actual_owner_sequence_are_required(self) -> None:
        owners = await CurrentRuntimeResourceOwners.inspect_owners(
            self.project, (self.scope,), node_resources=self.peer()
        )
        proof = owners.verify_current_scope(project_uuid=self.project, scope=self.scope)
        assert proof is not None
        self.assertEqual(proof.revision, 7)
        self.assertEqual(proof.grant.resource_id, self.binding.resource_id)
        self.assertIsNone(owners.verify_current_scope(project_uuid=uuid4(), scope=self.scope))
        wrong = replace(
            self.scope, resource_id=workspace_resource(self.node, self.project, uuid4())
        )
        with self.assertRaises(ValueError):
            await CurrentRuntimeResourceOwners.inspect_owners(
                self.project, (wrong,), node_resources=self.peer()
            )

    async def test_stale_other_project_and_unbound_owner_projections_fail_closed(self) -> None:
        original = self.binding
        for changed in (
            original.model_copy(update={"expires_at": int(time.time()) - 1}),
            original.model_copy(update={"project_uuid": uuid4()}),
            original.model_copy(
                update={"resource_id": workspace_resource(self.node, self.project, uuid4())}
            ),
            original.model_copy(update={"resource_revision": 0}),
        ):
            self.binding = changed
            with self.assertRaises(ValueError):
                await CurrentRuntimeResourceOwners.node_files(self.peer(), self.project)

    async def test_terminal_uses_its_own_module_and_workspace_selector(self) -> None:
        from node_protocol.terminal import workspace_resource as terminal_resource

        self.binding = self.binding.model_copy(
            update={"resource_id": terminal_resource(self.node, self.project, self.workspace)}
        )
        scope = SessionResourceGrant(
            "terminal", "terminal_exec", "terminal.execute", "workspace", self.binding.resource_id
        )
        owners = await CurrentRuntimeResourceOwners.inspect_owners(
            self.project, (scope,), node_resources=self.peer("terminal")
        )
        proof = owners.verify_current_scope(project_uuid=self.project, scope=scope)
        assert proof is not None
        self.assertEqual(proof.revision, 7)
        self.assertEqual(proof.grant.hand, "terminal")
        self.binding = self.binding.model_copy(
            update={"resource_id": workspace_resource(self.node, self.project, self.workspace)}
        )
        with self.assertRaises(ValueError):
            await CurrentRuntimeResourceOwners.inspect_owners(
                self.project, (scope,), node_resources=self.peer("terminal")
            )

    async def test_all_module_resources_need_their_own_current_binding(self) -> None:
        from node_protocol.module_effects import MODULES, RESOURCE_KINDS, effect_action, resource_id

        selected = {
            "files": "file_read",
            "terminal": "terminal_exec",
            "web": "browser_open",
            "svc": "github_accounts",
            "infrastructure": "observability_sources",
            "reverse": "list_projects",
            "serena": "get_symbols_overview",
        }
        for module in sorted(MODULES):
            with self.subTest(module=module):
                self.binding = self.binding.model_copy(
                    update={
                        "resource_id": resource_id(module, self.node, self.project, self.workspace)
                    }
                )
                tool = selected[module]
                scope = SessionResourceGrant(
                    module,
                    tool,
                    effect_action(module, tool),
                    RESOURCE_KINDS[module],
                    self.binding.resource_id,
                )
                owners = await CurrentRuntimeResourceOwners.inspect_owners(
                    self.project, (scope,), node_resources=self.peer(module)
                )
                proof = owners.verify_current_scope(project_uuid=self.project, scope=scope)
                assert proof is not None
                self.assertEqual(
                    (proof.grant.hand, proof.grant.tool, proof.revision), (module, tool, 7)
                )
                self.binding = self.binding.model_copy(
                    update={"resource_id": resource_id(module, self.node, self.project, uuid4())}
                )
                with self.assertRaises(ValueError):
                    await CurrentRuntimeResourceOwners.inspect_owners(
                        self.project, (scope,), node_resources=self.peer(module)
                    )

    async def test_missing_node_owner_never_borrows_a_legacy_owner(self) -> None:
        with self.assertRaises(ValueError):
            await CurrentRuntimeResourceOwners.inspect_owners(self.project, (self.scope,))

    async def test_new_hand_request_models_and_reserved_project_names_are_exact(self) -> None:
        from authorization._decision_api import DecisionCommand
        from authorization._rauthy_access_commands import ScopeEffect
        from authorization._resource_scope import EffectResource, validate_project_resource_scope
        from node_protocol.module_effects import RESOURCE_KINDS, effect_action, resource_id

        cases: tuple[tuple[HandName, str], ...] = (
            ("reverse", "radare2_binary_info"),
            ("serena", "get_symbols_overview"),
        )
        for module, tool in cases:
            resource = EffectResource(
                kind=RESOURCE_KINDS[module],
                id=resource_id(module, self.node, self.project, self.workspace),
            )
            ScopeEffect.model_validate(
                {
                    "hand": module,
                    "tool": tool,
                    "action": effect_action(module, tool),
                    "resource": resource.model_dump(),
                }
            )
            DecisionCommand(
                project_uuid=self.project,
                agent_session_uuid=uuid4(),
                expected_grant_revision=1,
                action=effect_action(module, tool),
                hand=module,
                tool=tool,
                resource=resource,
            )
            with self.assertRaises(ValueError):
                validate_project_resource_scope(
                    project_uuid=uuid4(), hand=module, tool=tool, resource=resource
                )
            with self.assertRaises(ValueError):
                DecisionCommand(
                    project_uuid=self.project,
                    agent_session_uuid=uuid4(),
                    expected_grant_revision=1,
                    action="files.read",
                    hand=module,
                    tool=tool,
                    resource=resource,
                )
