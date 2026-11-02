"""Resources-owned SQL projection with exact row and provenance validation."""

from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict
from projects._resource_persistence import IntegrationRow, VariableRow
from projects.domain.catalog_metadata import (
    CatalogMetadataEntry,
    CatalogMetadataKind,
    CatalogMetadataOwnerUnavailable,
    CatalogMetadataSelection,
    CatalogResourceSummary,
    VerifiedCatalogViewer,
    require_catalog_owner,
)
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding


def catalog_row_uuid(value: object) -> UUID:
    if not isinstance(value, UUID) or value.version != 4:
        raise CatalogMetadataOwnerUnavailable("unverified Catalog row")
    return value


def catalog_display_key(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise CatalogMetadataOwnerUnavailable("invalid Catalog display key")
    return value


def metadata_entry(
    row: IntegrationRow | VariableRow, viewer: VerifiedCatalogViewer, kind: CatalogMetadataKind
) -> CatalogMetadataEntry:
    row_uuid = catalog_row_uuid(row.id)
    if row.deleted_at is not None or type(row.version) is not int or row.version < 1:
        raise CatalogMetadataOwnerUnavailable("unverified Catalog row")
    require_catalog_owner(row.owner_project_id, row.owner_team_id, viewer)
    owner_uuid = row.owner_project_id or row.owner_team_id
    if owner_uuid is None:
        raise CatalogMetadataOwnerUnavailable("unverified Catalog row")
    return CatalogMetadataEntry(
        row_uuid,
        kind,
        "project" if row.owner_project_id is not None else "team",
        owner_uuid,
        catalog_display_key(row.alias_key if isinstance(row, IntegrationRow) else row.name_key),
        row.version,
    )


class SqlCatalogMetadataSource(_PrivateDatabaseBinding[PlatformDatabase]):
    async def read(
        self, viewer: VerifiedCatalogViewer, kind: CatalogMetadataKind, limit: int
    ) -> tuple[CatalogMetadataEntry, ...]:
        model = IntegrationRow if kind == "integration" else VariableRow
        conditions = [model.owner_project_id == viewer.project_uuid]
        if viewer.team_uuid is not None:
            conditions.append(model.owner_team_id == viewer.team_uuid)
        statement = (
            select(model)
            .where(or_(*conditions), model.deleted_at.is_(None))
            .order_by(model.id)
            .limit(limit + 1)
        )
        try:
            async with self._database.transaction() as tx:
                rows = list(await tx.scalars(statement))
        except Exception:
            raise CatalogMetadataOwnerUnavailable("Catalog owner SQL unavailable") from None
        if len(rows) > limit:
            raise CatalogMetadataOwnerUnavailable("Catalog source exceeds bounded page")
        result: list[CatalogMetadataEntry] = []
        seen: set[UUID] = set()
        for row in rows:
            if not isinstance(row, model):
                raise CatalogMetadataOwnerUnavailable("unverified Catalog row")
            entry = metadata_entry(row, viewer, kind)
            if entry.resource_uuid in seen:
                raise CatalogMetadataOwnerUnavailable("unverified Catalog row")
            seen.add(entry.resource_uuid)
            result.append(entry)
        return tuple(result)


def owned_metadata_summary(
    row: object, selection: CatalogMetadataSelection
) -> CatalogResourceSummary:
    if not isinstance(row, (IntegrationRow, VariableRow)):
        raise AccessDenied("Catalog source row type differs from selected resource")
    if (row.owner_team_id is None) == (row.owner_project_id is None):
        raise AccessDenied("Catalog resource violates XOR owner provenance")
    owner_id = row.owner_team_id or row.owner_project_id
    if owner_id is None:
        raise AccessDenied("Catalog resource violates XOR owner provenance")
    return CatalogResourceSummary(
        resource_id=row.id,
        resource_type="integration" if selection.kind == "integrations" else "variable",
        alias_key=row.alias_key if isinstance(row, IntegrationRow) else row.name_key,
        owner_scope="team" if row.owner_team_id is not None else "project",
        owner_id=owner_id,
        version=row.version,
    )


def owner_metadata_statement(
    selection: CatalogMetadataSelection,
) -> Select[tuple[IntegrationRow]] | Select[tuple[VariableRow]]:
    row_type = IntegrationRow if selection.kind == "integrations" else VariableRow
    column = IntegrationRow.alias_key if selection.kind == "integrations" else VariableRow.name_key
    filters = []
    if selection.scope in {"all", "project"}:
        filters.append(row_type.owner_project_id == selection.project_uuid)
    if selection.scope in {"all", "team"} and selection.team_uuid is not None:
        filters.append(row_type.owner_team_id == selection.team_uuid)
    if not filters:
        raise AccessDenied("Catalog Team scope not proven by current Control owner")
    statement: Select[tuple[IntegrationRow]] | Select[tuple[VariableRow]] = (
        select(IntegrationRow) if selection.kind == "integrations" else select(VariableRow)
    )
    statement = statement.where(or_(*filters), row_type.deleted_at.is_(None))
    if selection.alias_key is not None:
        statement = statement.where(column == selection.alias_key)
    return statement.order_by(row_type.id).limit(selection.limit + 1)


class SqlCatalogOwnerMetadata(_PrivateDatabaseBinding[PlatformDatabase]):
    async def read(self, selection: CatalogMetadataSelection) -> tuple[CatalogResourceSummary, ...]:
        async with self._database.transaction() as tx:
            return await self.read_in_transaction(tx, selection)

    async def read_in_transaction(
        self, tx: AsyncSession, selection: CatalogMetadataSelection
    ) -> tuple[CatalogResourceSummary, ...]:
        rows = list(await tx.scalars(owner_metadata_statement(selection)))
        if len(rows) > selection.limit:
            raise Conflict("Catalog list exceeds bounded page; use scoped pagination")
        return tuple(owned_metadata_summary(row, selection) for row in rows)
