"""Read bounded metadata while the independently verified owner lease is current."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.domain.catalog_metadata import (
    CatalogMetadataEntry,
    CatalogMetadataKind,
    CatalogMetadataOwnerUnavailable,
    VerifiedCatalogViewer,
)


class CatalogMetadataSource(Protocol):
    async def read(
        self, viewer: VerifiedCatalogViewer, kind: CatalogMetadataKind, limit: int
    ) -> tuple[CatalogMetadataEntry, ...]: ...


class ReadCatalogMetadata:
    def __init__(self, source: CatalogMetadataSource, clock: Callable[[], datetime]) -> None:
        self._source, self._clock = source, clock

    async def execute(
        self,
        viewer: VerifiedCatalogViewer,
        project_uuid: UUID,
        kind: CatalogMetadataKind,
        limit: int,
    ) -> tuple[CatalogMetadataEntry, ...]:
        viewer.require_current(project_uuid, self._clock())
        entries = await self._source.read(viewer, kind, limit)
        if viewer.expires_at <= self._clock():
            raise CatalogMetadataOwnerUnavailable("Catalog scope expired during owner read")
        return entries
