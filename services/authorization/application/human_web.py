"""Issue a short human effect only after independent identity and owner checks."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from authorization.domain.human_web import (
    HumanCall,
    HumanDecision,
    HumanIdentity,
    HumanLease,
    HumanResource,
)
from authorization.domain.workspace_effects import WorkspaceBinding


class HumanIdentities(Protocol):
    async def current(self) -> HumanIdentity: ...


class HumanBindings(Protocol):
    async def current(self) -> WorkspaceBinding: ...


class HumanResources(Protocol):
    async def current(
        self, identity: HumanIdentity, binding: WorkspaceBinding
    ) -> HumanResource: ...


class HumanPolicy(Protocol):
    def permits(self, decision: HumanDecision) -> bool: ...


class HumanSigner(Protocol):
    @property
    def public_key(self) -> str: ...

    def sign(self, lease: HumanLease) -> str: ...


class AuthorizeHumanEffect:
    def __init__(
        self,
        *,
        identities: HumanIdentities,
        bindings: HumanBindings,
        resources: HumanResources,
        policy: HumanPolicy,
        signer: HumanSigner,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.identities = identities
        self.bindings = bindings
        self.resources = resources
        self.policy = policy
        self.signer = signer
        self.clock = clock

    async def execute(self, call: HumanCall) -> str:
        identity = await self.identities.current()
        identity.require_current(call.project_uuid, self.clock())
        binding = await self.bindings.current()
        binding.require_human_current(
            call.project_uuid, self.signer.public_key, int(self.clock().timestamp())
        )
        resource = await self.resources.current(identity, binding)
        resource.require_call(call, binding)
        decision = HumanDecision(
            identity.identity.actor_uuid,
            call.project_uuid,
            binding.resource_id,
            True,
            True,
            call.action,
        )
        if not self.policy.permits(decision):
            raise PermissionError("Human browser policy denied")
        fresh = await self.identities.current()
        fresh.require_current(call.project_uuid, self.clock())
        if fresh.identity.actor_uuid != identity.identity.actor_uuid or (
            fresh.identity.issuer,
            fresh.identity.subject,
        ) != (identity.identity.issuer, identity.identity.subject):
            raise PermissionError("Human identity changed")
        now = int(self.clock().timestamp())
        expiry = min(
            now + 5,
            binding.expires_at,
            int(fresh.identity.actor_expires_at.timestamp()),
            int(fresh.identity.provider_expires_at.timestamp()),
        )
        if expiry <= now:
            raise PermissionError("Human browser authority expired")
        return self.signer.sign(HumanLease(call, fresh.identity, binding, now, expiry))
