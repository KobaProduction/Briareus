"""Compatibility exports for the shared project runtime client implementation."""

import asyncio as asyncio
import math as math
from typing import Literal as Literal
from typing import Protocol as Protocol
from uuid import UUID as UUID

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import model_validator as model_validator

from project_runtime_client.authorization import ProjectAccessDenied as ProjectAccessDenied
from project_runtime_client.authorization import ProjectInvocation as ProjectInvocation
from project_runtime_client.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.authorization import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from project_runtime_client.authorization import valid_project_revision as valid_project_revision
from project_runtime_client.catalog_metadata import CatalogMetadataModel as CatalogMetadataModel
from project_runtime_client.catalog_metadata import CatalogResourceAdapter as CatalogResourceAdapter
from project_runtime_client.catalog_metadata import CatalogResourcePort as CatalogResourcePort
from project_runtime_client.catalog_metadata import CatalogResourceView as CatalogResourceView
from project_runtime_client.catalog_metadata import OwnerKind as OwnerKind
from project_runtime_client.catalog_metadata import ResourceKind as ResourceKind
from project_runtime_client.domain.catalog_metadata import (
    CatalogResourceFacts as CatalogResourceFacts,
)
from project_runtime_client.domain.catalog_metadata import (
    require_current_catalog_permit as require_current_catalog_permit,
)
from project_runtime_client.integrations import IntegrationProvider as IntegrationProvider
from project_runtime_client.integrations import ProjectIntegrationError as ProjectIntegrationError
from project_runtime_client.integrations import ProjectIntegrationRef as ProjectIntegrationRef
from project_runtime_client.resource_scope import EffectiveResourceScope as EffectiveResourceScope
from project_runtime_client.variables import ProjectVariableRef as ProjectVariableRef
