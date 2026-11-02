"""HTTP query and public Catalog metadata projection."""

from dataclasses import asdict, dataclass
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api.application.catalog_metadata import CatalogFailure, ReadCatalogMetadata
from control_panel_api.domain.catalog_metadata import CatalogKind
from control_panel_api.domain.panel_protocol import PanelContext

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@dataclass(frozen=True, slots=True)
class CatalogOwner:
    kind: str
    id: str


@dataclass(frozen=True, slots=True)
class CatalogItem:
    resource_uuid: str
    kind: str
    owner: CatalogOwner
    key: str
    version: int


@dataclass(frozen=True, slots=True)
class CatalogItems:
    items: tuple[CatalogItem, ...]


@dataclass(frozen=True, slots=True)
class CatalogController:
    current_context: CurrentPlatformContext
    catalog: ReadCatalogMetadata

    async def list_metadata(
        self, request: Request, project_uuid: UUID, kind: CatalogKind
    ) -> JSONResponse:
        current = await self.current_context(request, project_uuid)
        if isinstance(current, JSONResponse):
            return current
        result = await self.catalog.execute(PanelContext(*current), project_uuid, kind)
        if isinstance(result, CatalogFailure):
            return JSONResponse(
                {"error": {"code": result.code}}, status_code=result.status, headers=HEADERS
            )
        document = CatalogItems(
            tuple(
                CatalogItem(
                    str(item.resource_uuid),
                    item.kind,
                    CatalogOwner(item.owner_kind, str(item.owner_uuid)),
                    item.key,
                    item.version,
                )
                for item in result.items
            )
        )
        return JSONResponse(asdict(document), headers=HEADERS)
