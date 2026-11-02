"""Compatibility imports for the resource domain public contract."""

from .domain.resource_scope import (
    EffectiveResourceScope,
    ProjectResourceScopeError,
    ResourceOrigin,
)

__all__ = [
    "EffectiveResourceScope",
    "ProjectResourceScopeError",
    "ResourceOrigin",
]
