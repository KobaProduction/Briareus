"""Compatibility imports for the resource domain public contract."""

from .domain.resource_query import (
    NamedResource,
    ResourceFilter,
    ResourceQuery,
    ResourceSelectionError,
    effective_collection,
    one_named_resource,
)

__all__ = [
    "NamedResource",
    "ResourceFilter",
    "ResourceQuery",
    "ResourceSelectionError",
    "effective_collection",
    "one_named_resource",
]
