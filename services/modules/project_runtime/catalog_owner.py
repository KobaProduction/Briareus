"""Owner-local compatibility and codec boundary for shared runtime clients."""

from __future__ import annotations

import hashlib as hashlib
from typing import Literal as Literal
from uuid import UUID as UUID

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field

from project_runtime_client.catalog_owner import CatalogListRequest as CatalogListRequest
from project_runtime_client.catalog_owner import CatalogListResult as CatalogListResult
from project_runtime_client.catalog_owner import CatalogOwnerSource as CatalogOwnerSource
from project_runtime_client.catalog_owner import (
    CatalogProviderReader as _SharedCatalogProviderReader,
)
from project_runtime_client.catalog_owner import CatalogResolveRequest as CatalogResolveRequest
from project_runtime_client.catalog_owner import CatalogResolveResult as CatalogResolveResult
from project_runtime_client.catalog_owner import catalog_target as catalog_target

from .a6_provider import ProviderReadCommand as ProviderReadCommand
from .a6_provider import ProviderReadReceipt as ProviderReadReceipt
from .authorization import ProjectInvocation as ProjectInvocation
from .authorization import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from .authorization import valid_project_revision as valid_project_revision
from .catalog_metadata import CatalogResourcePort as CatalogResourcePort
from .catalog_metadata import CatalogResourceView as CatalogResourceView
from .catalog_metadata import ResourceKind as ResourceKind
from .domain.identifiers import valid_uuid as valid_uuid
from .owner_effects import OwnerEffectClient as OwnerEffectClient
from .owner_effects import OwnerEffectUnavailable as OwnerEffectUnavailable

CatalogProviderReader = _SharedCatalogProviderReader
