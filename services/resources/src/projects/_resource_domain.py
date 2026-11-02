"""Reusable Team/Project resource vocabulary; not Project or Team aggregates.

A resource has exactly one owner. A Project receives Team-owned resources only
by current Team ownership and current authorization; no copies or overrides.
"""

from __future__ import annotations

import re as re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from common.platform_errors import AccessDenied, InvalidInput
from common.platform_ids import PlatformProjectId, TeamId
from projects.catalog.domain.resource_values import (
    _ResourceNames,
    _ResourceOrigin,
    _ResourceOwnerProperties,
)
from runtime_peer.domain.provider_settings import ProviderSettings


class ResourceScope(StrEnum):
    ALL = "all"
    TEAM = "team"
    PROJECT = "project"


class OwnerScope(StrEnum):
    TEAM = "team"
    PROJECT = "project"


class ResourceKind(StrEnum):
    INTEGRATION = "integration"
    VARIABLE = "variable"


@dataclass(frozen=True, slots=True)
class ResourceOwner(_ResourceOwnerProperties[OwnerScope, TeamId, PlatformProjectId]):
    scope: OwnerScope
    owner_id: UUID

    _team_scope = OwnerScope.TEAM
    _project_scope = OwnerScope.PROJECT
    _team_factory = staticmethod(TeamId)
    _project_factory = staticmethod(PlatformProjectId)

    def matches(self, team_id: UUID | None, project_id: UUID | None) -> bool:
        return team_id == self.team_id and project_id == self.project_id

    def require_lease_revisions(
        self,
        expected_team_id: UUID | None,
        team_revision: int | None,
        team_resource_revision: int | None,
    ) -> None:
        if self.scope is OwnerScope.TEAM:
            valid = (
                expected_team_id == self.owner_id
                and team_revision is not None
                and team_resource_revision is not None
            )
        else:
            valid = (
                expected_team_id is None
                and team_revision is None
                and team_resource_revision is None
            )
        if not valid:
            raise AccessDenied("Catalog ownership revision proof incomplete or inconsistent")


@dataclass(frozen=True, slots=True)
class EffectiveResource(_ResourceOrigin[OwnerScope, TeamId, PlatformProjectId]):
    resource_id: UUID
    kind: ResourceKind
    owner: ResourceOwner
    name: str
    key: str
    version: int
    inherited: bool
    is_secret: bool
    provider: str | None = None
    auth_type: str | None = None
    value: str | None = None
    display_name: str = ""
    provider_settings: ProviderSettings | None = None
    credential_configured: bool = False
    connection_status: str | None = None
    updated_at: datetime | None = None


class AmbiguousResource(InvalidInput):
    code = "resource_ambiguous"
    status_code = 409


_resource_names = _ResourceNames(InvalidInput)
canonical_alias = _resource_names.canonical_alias
canonical_variable_name = _resource_names.canonical_variable_name
