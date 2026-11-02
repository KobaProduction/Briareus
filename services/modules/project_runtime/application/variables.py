"""Compatibility exports for the shared project runtime client implementation."""

import asyncio as asyncio
import math as math
from typing import Protocol as Protocol
from uuid import UUID as UUID

from project_runtime_client.application.resource_authority import (
    ResourceAuthorityPort as ResourceAuthorityPort,
)
from project_runtime_client.application.variables import ProjectVariablePort as ProjectVariablePort
from project_runtime_client.application.variables import (
    ProjectVariableSelector as ProjectVariableSelector,
)
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
from project_runtime_client.domain.resources import ProjectVariableError as ProjectVariableError
from project_runtime_client.domain.resources import ProjectVariableRef as ProjectVariableRef
from project_runtime_client.domain.revisions import valid_project_revision as valid_project_revision
