"""Obtain fresh identity, binding, every continuation grant and private context."""

import hashlib
import time
from dataclasses import dataclass, replace
from typing import Protocol

from authorization.domain.decisions import AuthorizedCurrentGrant
from authorization.domain.workspace_effects import (
    PrivateInvocation,
    WorkspaceBinding,
    WorkspaceCall,
    WorkspaceEffectLease,
    WorkspaceGrantDenied,
    WorkspaceIdentity,
    lease_expiry,
)


class WorkspaceIdentityPort(Protocol):
    async def current(self) -> WorkspaceIdentity: ...


class WorkspaceBindingPort(Protocol):
    async def current(self) -> WorkspaceBinding: ...


class WorkspaceGrantPort(Protocol):
    async def current(
        self,
        identity: WorkspaceIdentity,
        binding: WorkspaceBinding,
        tool: str | None,
    ) -> AuthorizedCurrentGrant | None: ...


class PrivateInvocationPort(Protocol):
    async def current(
        self,
        identity: WorkspaceIdentity,
        binding: WorkspaceBinding,
        grant: AuthorizedCurrentGrant,
    ) -> PrivateInvocation: ...


class WorkspaceEffectSignerPort(Protocol):
    def sign(self, lease: WorkspaceEffectLease) -> str: ...


@dataclass(frozen=True, slots=True)
class WorkspaceAuthorization:
    permit: str
    private_context: bytes


class AuthorizeWorkspaceEffect:
    def __init__(
        self,
        *,
        identities: WorkspaceIdentityPort,
        bindings: WorkspaceBindingPort,
        grants: WorkspaceGrantPort,
        invocations: PrivateInvocationPort,
        signer: WorkspaceEffectSignerPort,
        public_key: str,
    ) -> None:
        self.identities = identities
        self.bindings = bindings
        self.grants = grants
        self.invocations = invocations
        self.signer = signer
        self.public_key = public_key

    async def execute(self, call: WorkspaceCall) -> WorkspaceAuthorization:
        identity = await self.identities.current()
        binding = await self.bindings.current()
        binding.require_current(call, self.public_key, int(time.time()))
        grant = await self._current_grants(call, identity, binding)
        invocation = PrivateInvocation(b"", binding.expires_at)
        if call.module in {"svc", "infrastructure"} and call.tool is not None:
            invocation = await self.invocations.current(identity, binding, grant)
        now = int(time.time())
        lease = WorkspaceEffectLease(
            call,
            identity,
            binding,
            grant.grant_revision,
            now,
            lease_expiry(now, grant.expires_at, binding, invocation),
            hashlib.sha256(invocation.context).hexdigest() if invocation.context else "",
        )
        return WorkspaceAuthorization(self.signer.sign(lease), invocation.context)

    async def _current_grants(
        self,
        call: WorkspaceCall,
        identity: WorkspaceIdentity,
        binding: WorkspaceBinding,
    ) -> AuthorizedCurrentGrant:
        current = await self.grants.current(identity, binding, call.tool)
        if current is None:
            raise WorkspaceGrantDenied
        for tool in call.continuation_tools():
            original = await self.grants.current(identity, binding, tool)
            if original is None or original.grant_revision != current.grant_revision:
                raise WorkspaceGrantDenied
            current = replace(current, expires_at=min(current.expires_at, original.expires_at))
        return current
