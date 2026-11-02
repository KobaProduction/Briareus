"""Typed Project runtime public interface without eager provider imports.

Importing `modules.project_runtime` cannot pull Files, Terminal, Reverse,
Catalog, provider SDKs or unused Team resource selectors into another App.
Historical public symbols remain exact; access loads ONLY their owning
interface module. Service-owned handlers are registered in their entrypoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_runtime_client._lazy_exports import _EXPORT_MODULE as _EXPORT_MODULE
from project_runtime_client._lazy_exports import _LazyRuntimeExports

if TYPE_CHECKING:
    from .authorization import (
        ProjectAccessDenied,
        ProjectAccessPort,
        ProjectAction,
        ProjectInvocation,
        ProjectOperationScope,
        ProjectPermit,
        ProjectRuntimeAuthority,
        canonical_request_fingerprint,
    )
    from .integrations import (
        ProjectIntegrationError,
        ProjectIntegrationPort,
        ProjectIntegrationRef,
        ProjectIntegrationSelector,
    )
    from .resource_query import ResourceQuery, ResourceSelectionError
    from .resource_scope import EffectiveResourceScope, ProjectResourceScopeError
    from .variables import ProjectVariableError, ProjectVariableRef, ProjectVariableSelector
    from .workspace_roots import ProjectFileError, ProjectRootRegistry

_public_interface = _LazyRuntimeExports(__name__)
__getattr__ = _public_interface.resolve
__dir__ = _public_interface.names
__all__ = [
    "EffectiveResourceScope",
    "ProjectAccessDenied",
    "ProjectAccessPort",
    "ProjectAction",
    "ProjectFileError",
    "ProjectIntegrationError",
    "ProjectIntegrationPort",
    "ProjectIntegrationRef",
    "ProjectIntegrationSelector",
    "ProjectInvocation",
    "ProjectOperationScope",
    "ProjectPermit",
    "ProjectResourceScopeError",
    "ProjectRootRegistry",
    "ProjectRuntimeAuthority",
    "ProjectVariableError",
    "ProjectVariableRef",
    "ProjectVariableSelector",
    "ResourceQuery",
    "ResourceSelectionError",
    "canonical_request_fingerprint",
]
