"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass
from typing import Literal as Literal
from typing import Protocol as Protocol
from uuid import UUID as UUID

from project_runtime_client.domain.identifiers import valid_uuid as valid_uuid
from project_runtime_client.domain.resource_query import NamedResource as NamedResource
from project_runtime_client.domain.resource_query import ResourceFilter as ResourceFilter
from project_runtime_client.domain.resource_query import ResourceQuery as ResourceQuery
from project_runtime_client.domain.resource_query import (
    ResourceSelectionError as ResourceSelectionError,
)
from project_runtime_client.domain.resource_query import (
    _require_current_metadata as _require_current_metadata,
)
from project_runtime_client.domain.resource_query import (
    effective_collection as effective_collection,
)
from project_runtime_client.domain.resource_query import one_named_resource as one_named_resource
from project_runtime_client.domain.resource_scope import (
    EffectiveResourceScope as EffectiveResourceScope,
)
from project_runtime_client.domain.resource_scope import (
    ProjectResourceScopeError as ProjectResourceScopeError,
)
from project_runtime_client.domain.revisions import valid_project_revision as valid_project_revision
