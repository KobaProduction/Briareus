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

from common.platform_errors import InvalidInput
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
