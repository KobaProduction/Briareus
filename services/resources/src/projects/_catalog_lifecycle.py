"""Catalog-owned durable, encrypted-result metadata reads and lease abort.

Identity/Control/Access sign the exact immutable Project resource scope;
Catalog SQL selects only its own rows. Metadata never includes plaintext
credential, variable value, URLs, arbitrary provider JSON or secret hashes.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import SignedOwnerProofs, VerifiedOwnerOperation, require_signed_payload
from common.owner_transactions import OwnerCommandOutcome
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from projects._catalog_source import CatalogSourceService
from projects._resource_domain import OwnerScope, ResourceOwner
from projects._resource_persistence import IntegrationRow, VariableRow
from projects.application.owner_receipts import (
    CatalogListMetadataCommitted,
    CatalogMetadataRecord,
    CatalogResolveMetadataCommitted,
)
from projects.catalog.application._command_payloads import (
    ListCatalogMetadataPayload,
    ResolveCatalogMetadataPayload,
)
from projects.catalog.infrastructure.lifecycle import _CatalogLifecycleOperations
from projects.domain.catalog_metadata import CatalogMetadataSelection
from projects.infrastructure.catalog_metadata import SqlCatalogOwnerMetadata

Kind = Literal["integrations", "variables"]
Scope = Literal["all", "project", "team"]


class CatalogOwnerLifecycle(_CatalogLifecycleOperations, CatalogSourceService):
    async def list_metadata_committed(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        kind: Kind,
        scope: Scope = "all",
        alias_key: str | None = None,
        limit: int = 100,
    ) -> OwnerCommandOutcome[CatalogListMetadataCommitted]:
        """Exactly scoped durable read acknowledgement (not a credential grant)."""
        request = decision.request
        if (
            request.target_owner != "resources"
            or request.operation != f"catalog.{kind}.list"
            or not 1 <= limit <= 100
            or (
                alias_key is not None
                and (
                    not 1 <= len(alias_key) <= 128
                    or not all(c.isascii() and (c.isalnum() or c in "_.-") for c in alias_key)
                )
            )
            or (scope == "team" and request.expected_team_id is None)
        ):
            raise InvalidInput("Catalog list requires one approved source selector")
        require_signed_payload(
            request,
            asdict(
                ListCatalogMetadataPayload(kind=kind, scope=scope, alias_key=alias_key, limit=limit)
            ),
        )
        selection = CatalogMetadataSelection(
            request.project_id, request.expected_team_id, kind, scope, alias_key, limit
        )
        if not selection.has_scope:
            raise AccessDenied("Catalog Team scope not proven by current Control owner")

        async def mutation(tx: AsyncSession) -> CatalogListMetadataCommitted:
            selected = await SqlCatalogOwnerMetadata(self.db).read_in_transaction(tx, selection)
            values = [
                CatalogMetadataRecord(
                    resource_id=str(item.resource_id),
                    kind=kind,
                    owner_scope=item.owner_scope,
                    owner_id=str(item.owner_id),
                    name_key=item.alias_key,
                    version=item.version,
                )
                for item in selected
            ]
            if alias_key is not None and len(values) > 1:
                raise Conflict("equal Team/Project alias is ambiguous without exact owner")
            return CatalogListMetadataCommitted(
                status="recorded",
                kind=kind,
                scope=scope,
                alias_key=alias_key,
                limit=limit,
                project_id=str(request.project_id),
                records=values,
                count=len(values),
                source_secret_included=False,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="catalog.metadata_listed",
            target=kind,
            response_model=CatalogListMetadataCommitted,
        )

    async def resolve_metadata_committed(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        kind: Kind,
        resource_id: UUID,
        expected_resource_version: int,
        owner_scope: Literal["team", "project"],
        owner_id: UUID,
    ) -> OwnerCommandOutcome[CatalogResolveMetadataCommitted]:
        """Read exact resource owner+version with no alias fallback/secret."""
        request = decision.request
        if (
            request.target_owner != "resources"
            or request.operation != f"catalog.{kind}.resolve"
            or resource_id.version != 4
            or owner_id.version != 4
            or expected_resource_version < 1
            or (owner_scope == "team" and owner_id != request.expected_team_id)
            or (owner_scope == "project" and owner_id != request.project_id)
        ):
            raise AccessDenied("Catalog original Project/Team resource owner mismatch")
        require_signed_payload(
            request,
            asdict(
                ResolveCatalogMetadataPayload(
                    kind=kind,
                    resource_id=str(resource_id),
                    owner_scope=owner_scope,
                    owner_id=str(owner_id),
                    expected_resource_version=expected_resource_version,
                )
            ),
        )
        row_type = self._row(kind)
        owner = ResourceOwner(OwnerScope(owner_scope), owner_id)

        async def mutation(tx: AsyncSession) -> CatalogResolveMetadataCommitted:
            row = await tx.scalar(
                select(row_type).where(row_type.id == resource_id).with_for_update()
            )
            if row is not None and not isinstance(row, (IntegrationRow, VariableRow)):
                raise AccessDenied("Catalog source returned a foreign row")
            if (
                row is None
                or row.deleted_at is not None
                or row.version != expected_resource_version
                or not owner.matches(row.owner_team_id, row.owner_project_id)
            ):
                raise AccessDenied("Catalog resource gone, transferred or stale")
            return CatalogResolveMetadataCommitted(
                status="recorded",
                resource_id=str(row.id),
                owner_scope=owner_scope,
                owner_id=str(owner_id),
                name_key=row.alias_key if isinstance(row, IntegrationRow) else row.name_key,
                kind=kind,
                version=row.version,
                source_secret_included=False,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="catalog.metadata_resolved",
            target=str(resource_id),
            response_model=CatalogResolveMetadataCommitted,
        )
