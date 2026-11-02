"""Compatibility exports for the shared project runtime client implementation."""

import asyncio as asyncio
import math as math
from typing import Protocol as Protocol
from uuid import UUID as UUID

from project_runtime_client.application.integrations import (
    ProjectIntegrationPort as ProjectIntegrationPort,
)
from project_runtime_client.application.integrations import (
    ProjectIntegrationSelector as ProjectIntegrationSelector,
)
from project_runtime_client.application.resource_authority import (
    ResourceAuthorityPort as ResourceAuthorityPort,
)
from project_runtime_client.domain.authorization import ProjectAction as ProjectAction
from project_runtime_client.domain.authorization import ProjectInvocation as ProjectInvocation
from project_runtime_client.domain.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.domain.resource_query import ResourceFilter as ResourceFilter
from project_runtime_client.domain.resource_query import ResourceQuery as ResourceQuery
from project_runtime_client.domain.resource_query import (
    ResourceSelectionError as ResourceSelectionError,
)
from project_runtime_client.domain.resource_query import (
    effective_collection as effective_collection,
)
from project_runtime_client.domain.resource_query import one_named_resource as one_named_resource
from project_runtime_client.domain.resources import IntegrationOperation as IntegrationOperation
from project_runtime_client.domain.resources import IntegrationProvider as IntegrationProvider
from project_runtime_client.domain.resources import (
    ProjectIntegrationError as ProjectIntegrationError,
)
from project_runtime_client.domain.resources import ProjectIntegrationRef as ProjectIntegrationRef
from project_runtime_client.domain.resources import integration_action as integration_action
from project_runtime_client.domain.revisions import valid_project_revision as valid_project_revision
