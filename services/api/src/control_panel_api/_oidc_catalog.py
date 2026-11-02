"""Compose cookie-bound Catalog metadata, independently from executable resource grants."""

from fastapi import APIRouter

from ._api_paths import API_V1_PREFIX
from ._oidc_membership import CurrentPlatformContext
from .application.catalog_metadata import ReadCatalogMetadata
from .application.catalog_metadata import TrustedCatalogReadPort as TrustedCatalogReadPort
from .domain.catalog_metadata import CatalogReadDenied as CatalogReadDenied
from .domain.catalog_metadata import CatalogReadUnavailable as CatalogReadUnavailable
from .domain.catalog_metadata import VerifiedCatalogSummary as VerifiedCatalogSummary
from .presentation.catalog_metadata import CatalogController


def oidc_catalog_router(
    *,
    current_context: CurrentPlatformContext,
    catalog: TrustedCatalogReadPort | None,
) -> APIRouter:
    controller = CatalogController(current_context, ReadCatalogMetadata(catalog))
    router = APIRouter()
    router.add_api_route(API_V1_PREFIX + "/catalog", controller.list_metadata, methods=["GET"])
    return router
