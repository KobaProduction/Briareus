"""Current physical resource evidence obtained from authenticated Hand owners."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
import time

from runtime_peer import PeerClient, canonical_json

from authorization._resource_scope import EffectResource, VerifiedResourceOwnerProof, validate_effect_scope
from node_protocol.effect import NodeWorkspaceBinding


class CurrentRuntimeResourceOwners:
    def __init__(self, proofs: dict[bytes, VerifiedResourceOwnerProof]) -> None:
        self.proofs = proofs

    def verify_current_scope(self, *, project_uuid: UUID,
                             scope: dict[str, object]) -> VerifiedResourceOwnerProof | None:
        proof = self.proofs.get(canonical_json(scope))
        return (proof if proof is not None and proof.project_uuid == project_uuid
                and proof.expires_at > datetime.now(UTC) else None)

    @classmethod
    async def inspect_owners(cls, peers: dict[str, PeerClient | None], project: UUID,
                             scopes: list[dict[str, object]], node_resources=None) -> CurrentRuntimeResourceOwners:
        from node_protocol.module_effects import MODULES, RESOURCE_KINDS, TOOL_NAME, effect_action
        proofs = {}
        for hand in {scope.get("hand") for scope in scopes}:
            # A known Node Hand never silently falls back to a legacy owner or
            # borrows another Hand's physical storage/current resource proof.
            if hand not in MODULES or node_resources is None:
                raise ValueError("Current Node resource owner unavailable")
            binding = await cls.node_workspace(node_resources, project, hand)
            for scope in [item for item in scopes if item.get("hand") == hand]:
                tool = scope.get("tool")
                if not isinstance(tool, str) or TOOL_NAME.fullmatch(tool) is None:
                    raise ValueError("Exact bounded tool selector required")
                if hand == "files":
                    from node_protocol import files
                    if tool not in files.READ_TOOLS | getattr(files, "WRITE_TOOLS", frozenset()):
                        raise ValueError("Unknown Files effect scope")
                elif hand == "terminal":
                    from node_protocol.terminal import TOOLS
                    if tool not in TOOLS:
                        raise ValueError("Unknown Terminal effect scope")
                action = effect_action(hand, tool)
                resource = EffectResource.model_validate(scope["resource"])
                if (scope.get("action") != action or resource.kind != RESOURCE_KINDS[hand]
                    or resource.id != binding.resource_id):
                    raise ValueError("Scope belongs to another Node module storage")
                validate_effect_scope(hand, tool, action, resource)
                # This is current physical resource evidence for an EXACT
                # requested tool name, not proof that a dynamic tool exists.
                # The pinned worker SDK remains responsible for its catalogue.
                proofs[canonical_json(scope)] = VerifiedResourceOwnerProof(project, hand, tool,
                    action, resource, binding.resource_revision, datetime.fromtimestamp(binding.expires_at, UTC))
        return cls(proofs)

    @staticmethod
    async def node_files(peer, project):
        return await CurrentRuntimeResourceOwners.node_workspace(peer, project, "files")

    @staticmethod
    async def node_workspace(peer, project, module):
        from node_protocol.module_effects import MODULES, resource_id
        if module not in MODULES:
            raise ValueError("Approved Node module required")
        status,reply=await peer.call("/internal/v1/resources/node-"+module+"-authority",
            {"project_uuid":str(project),"module":module})
        if status!=200 or not isinstance(reply,dict) or set(reply)!={"binding"}:
            raise ValueError("Current node Files binding unavailable")
        binding=NodeWorkspaceBinding.model_validate(reply["binding"])
        now=time.time()
        if (binding.project_uuid!=project or not now<binding.expires_at<=now+5
            or binding.resource_id!=resource_id(module,binding.node_uuid,project,binding.workspace_uuid)):
            raise ValueError("Current node Files binding mismatch")
        return binding

    @classmethod
    async def inspect_terminal(cls, peer: PeerClient, project: UUID,
                                scopes: list[dict[str, object]]) -> CurrentRuntimeResourceOwners:
        began = datetime.now(UTC)
        status, reply = await peer.call("/internal/v1/terminal/inspect", {})
        if (status != 200 or reply.get("project_uuid") != str(project)
            or reply.get("isolated") is not True or type(reply.get("resource_revision")) is not int
            or reply["resource_revision"] < 1 or not isinstance(reply.get("tools"), list)
            or len(reply["tools"]) > 32
            or reply.get("resource_id") != "project-terminal:" + str(project) + ":" + format(reply["resource_revision"], "064x")):
            raise ValueError("Current isolated Terminal owner not verified")
        expires = began + timedelta(seconds=5)
        proofs = {}
        for scope in scopes:
            if scope.get("hand") != "terminal" or scope.get("tool") not in reply["tools"]:
                raise ValueError("Runtime resource owner not connected")
            resource = EffectResource.model_validate(scope["resource"])
            validate_effect_scope("terminal", scope["tool"], scope["action"], resource)
            if resource.kind != "workspace" or resource.id != reply["resource_id"]:
                raise ValueError("Terminal scope belongs to another project placement")
            proofs[canonical_json(scope)] = VerifiedResourceOwnerProof(
                project, "terminal", scope["tool"], scope["action"], resource,
                reply["resource_revision"], expires,
            )
        return cls(proofs)
