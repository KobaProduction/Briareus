"""Catalog visibility is owner metadata, never permission to execute an effect."""

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from control_panel_api.domain.approval_policy import uuid4 as _uuid_v4

from .platform_authority import PlatformProjectContext, ResolvedPlatformUser

CatalogKind = Literal["integration", "variable"]


@dataclass(frozen=True, slots=True)
class VerifiedCatalogSummary:
    resource_uuid: UUID
    kind: CatalogKind
    owner_kind: Literal["project", "team"]
    owner_uuid: UUID
    key: str
    version: int


class CatalogReadUnavailable(Exception):
    """The independent Catalog source is unavailable or returned invalid evidence."""


class CatalogReadDenied(Exception):
    """The Catalog owner rejected the current actor/project entitlement."""


def visible_project(proof: ResolvedPlatformUser, project: UUID) -> PlatformProjectContext | None:
    owned = tuple(
        item
        for item in proof.projects
        if item.project_uuid == project and "use_resources" in item.permissions
    )
    return owned[0] if len(owned) == 1 else None


def _version(value: object) -> bool:
    return type(value) is int and value >= 1


def _key(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value, re.ASCII) is not None
    )


def _catalog_shape(item: object, kind: CatalogKind, seen: set[UUID]) -> bool:
    return (
        isinstance(item, VerifiedCatalogSummary)
        and _uuid_v4(item.resource_uuid)
        and item.resource_uuid not in seen
        and item.kind == kind
        and item.owner_kind in {"team", "project"}
        and _uuid_v4(item.owner_uuid)
        and _version(item.version)
        and _key(item.key)
    )


def _catalog_owner(
    item: VerifiedCatalogSummary, project: PlatformProjectContext, proof: ResolvedPlatformUser
) -> bool:
    if item.owner_kind == "project":
        return item.owner_uuid == project.project_uuid
    return (
        project.owner_kind == "team"
        and project.owner_uuid == item.owner_uuid
        and any(team.team_uuid == item.owner_uuid for team in proof.teams)
    )


def valid_catalog_rows(
    items: object, kind: CatalogKind, project: PlatformProjectContext, proof: ResolvedPlatformUser
) -> bool:
    if not isinstance(items, tuple) or len(items) > 50:
        return False
    seen: set[UUID] = set()
    for item in items:
        if not isinstance(item, VerifiedCatalogSummary) or not _catalog_shape(item, kind, seen):
            return False
        if not _catalog_owner(item, project, proof):
            return False
        seen.add(item.resource_uuid)
    return True
