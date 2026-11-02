"""Compatibility exports for the shared project runtime client implementation."""

from project_runtime_client.domain.resource_scope import (
    EffectiveResourceScope as EffectiveResourceScope,
)
from project_runtime_client.domain.resource_scope import (
    ProjectResourceScopeError as ProjectResourceScopeError,
)
from project_runtime_client.domain.resource_scope import ResourceOrigin as ResourceOrigin
from project_runtime_client.resource_scope import __all__ as __all__
