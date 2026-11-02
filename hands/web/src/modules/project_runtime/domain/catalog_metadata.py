"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass
from typing import Literal as Literal
from typing import TypeGuard as TypeGuard
from uuid import UUID as UUID

from project_runtime_client.domain.authorization import ProjectAccessDenied as ProjectAccessDenied
from project_runtime_client.domain.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.domain.catalog_metadata import (
    CatalogResourceFacts as CatalogResourceFacts,
)
from project_runtime_client.domain.catalog_metadata import (
    _integration_provider as _integration_provider,
)
from project_runtime_client.domain.catalog_metadata import (
    require_current_catalog_permit as require_current_catalog_permit,
)
from project_runtime_client.domain.resource_scope import (
    EffectiveResourceScope as EffectiveResourceScope,
)
from project_runtime_client.domain.resources import IntegrationProvider as IntegrationProvider
from project_runtime_client.domain.resources import (
    ProjectIntegrationError as ProjectIntegrationError,
)
from project_runtime_client.domain.resources import ProjectIntegrationRef as ProjectIntegrationRef
from project_runtime_client.domain.resources import ProjectVariableRef as ProjectVariableRef
from project_runtime_client.domain.revisions import valid_project_revision as valid_project_revision
