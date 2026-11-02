"""Resolve one resource from the currently authorized Project catalog."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from common.platform_errors import AccessDenied, InvalidInput
from projects._resource_domain import (
    AmbiguousResource,
    EffectiveResource,
    ResourceKind,
    ResourceScope,
    canonical_alias,
    canonical_variable_name,
)


class AuthorizedProjectResources(Protocol):
    async def load(
        self, kind: ResourceKind, scope: ResourceScope
    ) -> tuple[EffectiveResource, ...]: ...


@dataclass(frozen=True)
class ResolveResourceQuery:
    kind: ResourceKind
    resource_id: UUID | None = None
    name: str | None = None
    scope: ResourceScope = ResourceScope.ALL


@dataclass(frozen=True)
class ResolveProjectResource:
    resources: AuthorizedProjectResources

    async def execute(self, query: ResolveResourceQuery) -> EffectiveResource:
        if (query.resource_id is None) == (query.name is None):
            raise InvalidInput("choose resource_id or name, never both")
        found = await self.resources.load(query.kind, query.scope)
        if query.resource_id is not None:
            matches = [item for item in found if item.resource_id == query.resource_id]
        else:
            matches = self._by_name(found, query)
        if not matches:
            raise AccessDenied("resource unavailable in selected Project")
        if len(matches) != 1:
            raise AmbiguousResource(
                "multiple authorized resources match; supply resource_id or explicit scope"
            )
        return matches[0]

    @staticmethod
    def _by_name(
        found: tuple[EffectiveResource, ...], query: ResolveResourceQuery
    ) -> list[EffectiveResource]:
        if query.name is None:
            raise InvalidInput("choose resource_id or name, never both")
        key = (
            canonical_alias(query.name)[1]
            if query.kind is ResourceKind.INTEGRATION
            else canonical_variable_name(query.name)
        )
        return [item for item in found if item.key == key]
