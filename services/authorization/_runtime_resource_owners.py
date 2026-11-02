"""Compatible owner-proof boundary over current evidence use cases and peer ports."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from authorization._resource_scope import VerifiedResourceOwnerProof
from authorization.application.runtime_owners import InspectRuntimeOwners
from authorization.domain.runtime_owners import RuntimeOwnerScope
from authorization.infrastructure.runtime_owners import (
    NodeRuntimeOwner,
    TerminalRuntimeOwner,
    node_workspace,
)
from node_protocol.effect import NodeWorkspaceBinding
from runtime_peer import PeerClient


class CurrentRuntimeResourceOwners:
    def __init__(self, proofs: dict[RuntimeOwnerScope, VerifiedResourceOwnerProof]) -> None:
        self.proofs = proofs

    def verify_current_scope(
        self, *, project_uuid: UUID, scope: RuntimeOwnerScope
    ) -> VerifiedResourceOwnerProof | None:
        proof = self.proofs.get(scope)
        if (
            proof is not None
            and proof.project_uuid == project_uuid
            and proof.expires_at > datetime.now(UTC)
        ):
            return proof
        return None

    @classmethod
    async def _inspect(
        cls,
        owner: NodeRuntimeOwner | TerminalRuntimeOwner,
        scopes: tuple[RuntimeOwnerScope, ...],
    ) -> CurrentRuntimeResourceOwners:
        evidence = await InspectRuntimeOwners(owner).execute(scopes)
        proofs = {}
        for entry in evidence:
            scope = entry.scope
            binding = entry.binding
            proofs[scope] = VerifiedResourceOwnerProof(
                binding.project_uuid, scope, binding.revision, binding.expires_at
            )
        return cls(proofs)

    @classmethod
    async def inspect_owners(
        cls,
        project: UUID,
        scopes: tuple[RuntimeOwnerScope, ...],
        node_resources: PeerClient | None = None,
    ) -> CurrentRuntimeResourceOwners:
        # Legacy peers cannot substitute an independently attested Node owner.
        return await cls._inspect(NodeRuntimeOwner(node_resources, project), scopes)

    @staticmethod
    async def node_files(peer: PeerClient, project: UUID) -> NodeWorkspaceBinding:
        return await node_workspace(peer, project, "files")

    @staticmethod
    async def node_workspace(peer: PeerClient, project: UUID, module: str) -> NodeWorkspaceBinding:
        return await node_workspace(peer, project, module)

    @classmethod
    async def inspect_terminal(
        cls, peer: PeerClient, project: UUID, scopes: tuple[RuntimeOwnerScope, ...]
    ) -> CurrentRuntimeResourceOwners:
        owner = TerminalRuntimeOwner(peer, project)
        if not scopes:
            await owner.inspect("terminal")
        return await cls._inspect(owner, scopes)
