"""Read bounded, independently scoped Catalog facts under the original authority deadline."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from control_panel_api.domain.catalog_metadata import (
    CatalogKind,
    CatalogReadDenied,
    VerifiedCatalogSummary,
    valid_catalog_rows,
    visible_project,
)
from control_panel_api.domain.panel_protocol import PanelContext
from service_runtime._reference_bindings import _OwnerBinding


class TrustedCatalogReadPort(Protocol):
    async def list_metadata(
        self, *, actor: UUID, project: UUID, kind: CatalogKind, limit: int
    ) -> tuple[VerifiedCatalogSummary, ...]: ...


@dataclass(frozen=True, slots=True)
class CatalogFailure:
    status: int
    code: str


@dataclass(frozen=True, slots=True)
class CatalogMetadata:
    items: tuple[VerifiedCatalogSummary, ...]


class ReadCatalogMetadata(_OwnerBinding[TrustedCatalogReadPort | None]):
    async def execute(
        self, context: PanelContext, project_uuid: UUID, kind: CatalogKind
    ) -> CatalogMetadata | CatalogFailure:
        if project_uuid.version != 4:
            return CatalogFailure(422, "CATALOG_PROJECT_INVALID")
        project = visible_project(context.proof, project_uuid)
        if project is None:
            return CatalogFailure(403, "CATALOG_PROJECT_PERMISSION_DENIED")
        if self._owner is None:
            return CatalogFailure(503, "CATALOG_SOURCE_UNAVAILABLE")
        try:
            items = await self._owner.list_metadata(
                actor=context.proof.user_uuid,
                project=project_uuid,
                kind=kind,
                limit=50,
            )
        except CatalogReadDenied:
            return CatalogFailure(403, "CATALOG_PROJECT_PERMISSION_DENIED")
        except Exception:
            return CatalogFailure(503, "CATALOG_SOURCE_UNAVAILABLE")
        if not valid_catalog_rows(items, kind, project, context.proof):
            return CatalogFailure(503, "CATALOG_SOURCE_INVALID_RESPONSE")
        if min(context.session.expires_at, context.proof.expires_at) <= datetime.now(UTC):
            return CatalogFailure(503, "CATALOG_PROOF_EXPIRED")
        return CatalogMetadata(items)
