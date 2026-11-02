"""Current Platform and physical placement admission for private provider custody."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from node_protocol.effect import NodeWorkspaceBinding
from node_protocol.provider_context import GitHubPolicy as GitHubPolicy
from node_protocol.provider_context import GitLabPolicy as GitLabPolicy
from node_protocol.provider_context import GitRuntimePolicy as GitRuntimePolicy
from node_protocol.provider_context import InvocationContext as InvocationContext
from node_protocol.provider_context import InvocationLease as PrivateInvocationResult
from node_protocol.provider_context import InvocationPolicies as InvocationPolicies
from node_protocol.provider_context import ProjectAccount as ProjectAccount
from projects.application.node_administration import PlatformActors
from projects.domain.node_administration import OperatorSelector, current_lease
from projects.domain.node_invocation import (
    ProviderCall,
    ProviderModule,
    ProviderSelection,
    select_provider,
)
from projects.domain.provider_connections import ConnectionFailure


@dataclass(frozen=True)
class NodeInvocation:
    selector: OperatorSelector
    module: ProviderModule
    call: ProviderCall
    binding: NodeWorkspaceBinding


class InvocationAccounts(Protocol):
    async def load(
        self, project_uuid: UUID, module: ProviderModule, selection: ProviderSelection
    ) -> InvocationContext: ...


class InvocationPlacement(Protocol):
    async def current(self, project_uuid: UUID, module: ProviderModule) -> NodeWorkspaceBinding: ...


class PrepareNodeInvocation:
    def __init__(
        self,
        platform: PlatformActors,
        placements: InvocationPlacement,
        accounts: InvocationAccounts,
        now: Callable[[], datetime],
    ) -> None:
        self._platform, self._placements, self._accounts, self._now = (
            platform,
            placements,
            accounts,
            now,
        )

    async def execute(self, command: NodeInvocation) -> PrivateInvocationResult:
        current = self._now()
        if (
            not current_lease(command.selector.identity_expires_at, current)
            or command.binding.project_uuid != command.selector.project_uuid
            or not current.timestamp() < command.binding.expires_at <= current.timestamp() + 5
        ):
            raise ConnectionFailure(403, "Current project invocation required")
        expiry = await self._membership(command.selector)
        actual = await self._placements.current(command.selector.project_uuid, command.module)
        if actual.model_copy(update={"expires_at": command.binding.expires_at}) != command.binding:
            raise ConnectionFailure(403, "Current project placement changed")
        selection = select_provider(command.module, command.call)
        context = await self._accounts.load(
            command.selector.project_uuid, command.module, selection
        )
        deadline = min(command.selector.identity_expires_at, expiry).timestamp()
        now = self._now().timestamp()
        expires = min(int(now) + 5, int(deadline), actual.expires_at, command.binding.expires_at)
        if expires <= now:
            raise ConnectionFailure(403, "Current invocation expired")
        return PrivateInvocationResult(context=context, expires_at=expires)

    async def _membership(self, selector: OperatorSelector) -> datetime:
        found = await self._platform.read(selector)
        if found.status != 200:
            raise ConnectionFailure(
                403 if found.status == 403 else 503, "Current Platform membership unavailable"
            )
        evidence = found.evidence
        if (
            evidence is None
            or evidence.issuer != selector.issuer
            or evidence.subject != selector.subject
            or evidence.actor_uuid != str(selector.actor_uuid)
            or evidence.project_uuid != str(selector.project_uuid)
            or "use_resources" not in evidence.permissions
            or not current_lease(evidence.expires_at, self._now())
        ):
            raise ConnectionFailure(403, "Current project resource access required")
        return evidence.expires_at
