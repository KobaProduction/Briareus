"""Resolve independent physical owners before validating exact requested effects."""

from typing import Protocol

from authorization.application._reference_bindings import _OwnerBinding
from authorization.domain.runtime_owners import (
    RuntimeOwnerBinding,
    RuntimeOwnerEvidence,
    RuntimeOwnerScope,
    RuntimeOwnerTool,
    bind_owner_scope,
)


class RuntimeOwnerPort(Protocol):
    async def inspect(self, hand: str) -> RuntimeOwnerBinding: ...

    def describe(self, scope: RuntimeOwnerScope) -> RuntimeOwnerTool: ...


class InspectRuntimeOwners(_OwnerBinding[RuntimeOwnerPort]):
    async def execute(
        self, scopes: tuple[RuntimeOwnerScope, ...]
    ) -> tuple[RuntimeOwnerEvidence, ...]:
        evidence = []
        for hand in {scope.hand for scope in scopes}:
            binding = await self._owner.inspect(hand)
            for scope in scopes:
                if scope.hand == hand:
                    tool = self._owner.describe(scope)
                    evidence.append(bind_owner_scope(scope, binding, tool))
        return tuple(evidence)
