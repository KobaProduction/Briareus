"""Rauthy-only, signed private Project/Team Catalog metadata inventory.

Resource Catalog keeps credentials and variable values inside its own DB.
A Project+Team owner proof comes from a separate authenticated Platform
service: neither browser UUIDs nor a Rauthy user JWT grants raw Catalog rows.
Results are NOT executable Hand resource grants; exact runtime ownership is
a separate Resource/Hand attestation at each effect.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from common.platform_db import PlatformDatabase
from projects.application.catalog_metadata import ReadCatalogMetadata
from projects.domain.catalog_metadata import CatalogMetadataEntry
from projects.domain.catalog_metadata import (
    CatalogMetadataOwnerDenied as CatalogMetadataOwnerDenied,
)
from projects.domain.catalog_metadata import (
    CatalogMetadataOwnerUnavailable as CatalogMetadataOwnerUnavailable,
)
from projects.domain.catalog_metadata import (
    VerifiedCatalogViewer as VerifiedCatalogViewer,
)
from projects.infrastructure.catalog_metadata import SqlCatalogMetadataSource
from projects.infrastructure.catalog_metadata import (
    catalog_display_key as catalog_display_key,
)
from projects.infrastructure.catalog_metadata import (
    catalog_row_uuid as catalog_row_uuid,
)

_MAX_ITEMS = 50


class CatalogListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    kind: Literal["integration", "variable"]
    limit: int = Field(ge=1, le=_MAX_ITEMS)

    @field_validator("project_uuid")
    @classmethod
    def project_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("current Catalog Project must be UUIDv4")
        return value


class TrustedCatalogReaderAttestor(Protocol):
    async def verify(self, request: Request, query: CatalogListQuery) -> VerifiedCatalogViewer:
        """Verify signed actor, private service peer and current owner scope."""
        ...


_VIEWER_ADAPTER = TypeAdapter(VerifiedCatalogViewer)


def verified_viewer(value: object) -> VerifiedCatalogViewer:
    if not isinstance(value, VerifiedCatalogViewer):
        raise CatalogMetadataOwnerDenied("current Project resources denied")
    try:
        # Dataclass annotations do not validate runtime values. Reconstruct from
        # fields so the decoder checks even an existing, malformed instance.
        return _VIEWER_ADAPTER.validate_python(asdict(value), strict=True)
    except ValidationError:
        raise CatalogMetadataOwnerDenied("current Project resources denied") from None


class CatalogMetadataReader:
    """Bounded Catalog SQL-only projection of nonsecret resource metadata."""

    def __init__(
        self, *, database: PlatformDatabase, attestor: TrustedCatalogReaderAttestor
    ) -> None:
        if database.engine.url.database != "briareus_resources" or attestor is None:
            raise ValueError("Rauthy catalog reader requires its own DB and trusted owner")
        self._db = database
        self._attestor = attestor

    async def list(
        self, request: Request, query: CatalogListQuery
    ) -> tuple[CatalogMetadataEntry, ...]:
        if (
            len(request.headers.getlist("authorization")) != 1
            or request.headers.getlist("cookie")
            or request.headers.getlist("origin")
            or request.headers.getlist("content-type") != ["application/json"]
        ):
            raise CatalogMetadataOwnerDenied("private Catalog service peer required")
        try:
            actor = verified_viewer(await self._attestor.verify(request, query))
        except CatalogMetadataOwnerDenied:
            raise
        except Exception:
            raise CatalogMetadataOwnerUnavailable("catalog actor/source unavailable") from None
        use_case = ReadCatalogMetadata(
            SqlCatalogMetadataSource(self._db), lambda: datetime.now(UTC)
        )
        return await use_case.execute(actor, query.project_uuid, query.kind, query.limit)


def private_catalog_reader_router(
    *,
    reader: CatalogMetadataReader | None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/resources/catalog", tags=["resources-private"])

    @router.post("/list", include_in_schema=False)
    async def list_resources(query: CatalogListQuery, request: Request) -> JSONResponse:
        if reader is None:
            return JSONResponse(
                {"error": {"code": "CATALOG_SOURCE_UNAVAILABLE"}},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        try:
            items = await reader.list(request, query)
        except CatalogMetadataOwnerDenied:
            return JSONResponse(
                {"error": {"code": "CATALOG_PROJECT_DENIED"}},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return JSONResponse(
                {"error": {"code": "CATALOG_SOURCE_UNAVAILABLE"}},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            {
                "items": [
                    {
                        "resource_uuid": str(item.resource_uuid),
                        "kind": item.kind,
                        "owner": {"kind": item.owner_kind, "id": str(item.owner_uuid)},
                        "key": item.key,
                        "version": item.version,
                    }
                    for item in items
                ]
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    return router
