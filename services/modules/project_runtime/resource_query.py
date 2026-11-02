"""Compatibility exports for the shared project runtime client implementation."""

from project_runtime_client.domain.resource_query import NamedResource as NamedResource
from project_runtime_client.domain.resource_query import ResourceFilter as ResourceFilter
from project_runtime_client.domain.resource_query import ResourceQuery as ResourceQuery
from project_runtime_client.domain.resource_query import (
    ResourceSelectionError as ResourceSelectionError,
)
from project_runtime_client.domain.resource_query import (
    effective_collection as effective_collection,
)
from project_runtime_client.domain.resource_query import one_named_resource as one_named_resource
from project_runtime_client.resource_query import __all__ as __all__
