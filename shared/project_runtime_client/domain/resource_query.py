"""Private Team/Project resource selection with explicit origin and ambiguity.

The backend port must provide an already authorized *effective collection* for
one Project. This layer checks every record and never guesses same-name items.
It does not retrieve credentials or expose a new MCP operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from project_runtime_client.domain._code_error import _CodeError

from .identifiers import valid_uuid
from .resource_scope import EffectiveResourceScope, ProjectResourceScopeError
from .revisions import valid_project_revision

ResourceFilter = Literal["all", "team", "project"]


class ResourceSelectionError(_CodeError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceQuery:
    scope: ResourceFilter = "all"
    owner_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.scope not in {"all", "team", "project"}:
            raise ResourceSelectionError("RESOURCE_SCOPE_INVALID")
        if self.owner_id is not None and (not valid_uuid(self.owner_id) or self.scope == "all"):
            raise ResourceSelectionError("RESOURCE_OWNER_FILTER_INVALID")

    def includes(self, scope: EffectiveResourceScope) -> bool:
        if self.scope != "all" and self.scope != scope.origin:
            return False
        return self.owner_id is None or scope.owner_id == self.owner_id


class NamedResource(Protocol):
    @property
    def scope(self) -> EffectiveResourceScope: ...

    @property
    def name(self) -> str: ...


def _require_current_metadata(
    record: NamedResource,
    *,
    project_id: UUID,
    access_revision: str,
) -> None:
    if not isinstance(record.name, str):
        raise ResourceSelectionError("RESOURCE_METADATA_INVALID")
    if not record.name.strip():
        raise ResourceSelectionError("RESOURCE_METADATA_INVALID")
    try:
        record.scope.verify_for(project_id)
    except (ProjectResourceScopeError, AttributeError, TypeError) as exc:
        raise ResourceSelectionError("RESOURCE_ACCESS_DENIED") from exc
    if record.scope.project_access_revision != access_revision:
        raise ResourceSelectionError("RESOURCE_ACCESS_STALE")


def effective_collection[TResource: NamedResource](
    records: tuple[TResource, ...],
    *,
    project_id: UUID,
    access_revision: str,
    query: ResourceQuery,
    max_items: int = 1000,
) -> tuple[TResource, ...]:
    """Validate the entire authorized collection BEFORE filtering or returning it.

    No partial result is leaked if even one item has forged provenance or a
    stale membership version. Duplicate aliases survive (no implicit merge).
    """
    if not valid_project_revision(access_revision):
        raise ResourceSelectionError("RESOURCE_ACCESS_REVISION_INVALID")
    if len(records) > max_items or max_items < 1:
        raise ResourceSelectionError("RESOURCE_COLLECTION_TOO_LARGE")
    visible: list[TResource] = []
    for record in records:
        _require_current_metadata(record, project_id=project_id, access_revision=access_revision)
        if query.includes(record.scope):
            visible.append(record)
    return tuple(visible)


def one_named_resource[TResource: NamedResource](
    records: tuple[TResource, ...],
    *,
    name: str,
) -> TResource:
    if not name.strip():
        raise ResourceSelectionError("RESOURCE_NAME_REQUIRED")
    matches = [record for record in records if record.name.casefold() == name.casefold()]
    if not matches:
        raise ResourceSelectionError("RESOURCE_NOT_FOUND")
    if len(matches) > 1:
        raise ResourceSelectionError("RESOURCE_NAME_AMBIGUOUS")
    return matches[0]
