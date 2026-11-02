"""Catalog metadata carries ownership provenance, never execution grants or secrets."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

type CatalogMetadataKind = Literal["integration", "variable"]
type CatalogCollection = Literal["integrations", "variables"]
type CatalogReadScope = Literal["all", "project", "team"]


@dataclass(frozen=True, slots=True)
class CatalogResourceSummary:
    """Owner metadata only, without credentials or provider configuration."""

    resource_id: UUID
    resource_type: CatalogMetadataKind
    alias_key: str
    owner_scope: Literal["team", "project"]
    owner_id: UUID
    version: int


@dataclass(frozen=True)
class CatalogMetadataSelection:
    project_uuid: UUID
    team_uuid: UUID | None
    kind: CatalogCollection
    scope: CatalogReadScope
    alias_key: str | None
    limit: int

    @property
    def has_scope(self) -> bool:
        return self.scope in {"all", "project"} or (
            self.scope == "team" and self.team_uuid is not None
        )


class CatalogMetadataOwnerUnavailable(Exception):
    """Cannot obtain a fresh private owner/source proof."""


class CatalogMetadataOwnerDenied(Exception):
    """Current Project/Team resource scope not authorized."""


@dataclass(frozen=True, slots=True)
class VerifiedCatalogViewer:
    actor_uuid: UUID
    project_uuid: UUID
    team_uuid: UUID | None
    can_use_resources: bool
    issuer: Literal["rauthy"]
    audience: Literal["briareus:resources"]
    expires_at: datetime

    def require_current(self, project_uuid: UUID, now: datetime) -> None:
        if (
            self.actor_uuid.version != 4
            or self.project_uuid != project_uuid
            or (self.team_uuid is not None and self.team_uuid.version != 4)
            or self.can_use_resources is not True
            or self.expires_at.tzinfo is None
            or not now < self.expires_at <= now + timedelta(seconds=30)
        ):
            raise CatalogMetadataOwnerDenied("current Project resources denied")


@dataclass(frozen=True)
class CatalogMetadataEntry:
    resource_uuid: UUID
    kind: CatalogMetadataKind
    owner_kind: Literal["project", "team"]
    owner_uuid: UUID
    key: str
    version: int


def require_catalog_owner(
    owner_project: UUID | None, owner_team: UUID | None, viewer: VerifiedCatalogViewer
) -> None:
    if (
        (owner_project is None) == (owner_team is None)
        or (owner_project is not None and owner_project != viewer.project_uuid)
        or (owner_team is not None and (viewer.team_uuid is None or owner_team != viewer.team_uuid))
    ):
        raise CatalogMetadataOwnerUnavailable("unverified Catalog row")
