"""Lazy public exports bound to the importing runtime compatibility package."""

from collections.abc import Collection
from importlib import import_module
from sys import modules
from types import ModuleType

_EXPORT_MODULE: dict[str, str] = {
    "EffectiveResourceScope": "resource_scope",
    "ProjectAccessDenied": "authorization",
    "ProjectAccessPort": "authorization",
    "ProjectAction": "authorization",
    "ProjectFileError": "workspace_roots",
    "ProjectIntegrationError": "integrations",
    "ProjectIntegrationPort": "integrations",
    "ProjectIntegrationRef": "integrations",
    "ProjectIntegrationSelector": "integrations",
    "ProjectInvocation": "authorization",
    "ProjectOperationScope": "authorization",
    "ProjectPermit": "authorization",
    "ProjectResourceScopeError": "resource_scope",
    "ProjectRootRegistry": "workspace_roots",
    "ProjectRuntimeAuthority": "authorization",
    "ProjectVariableError": "variables",
    "ProjectVariableRef": "variables",
    "ProjectVariableSelector": "variables",
    "ResourceQuery": "resource_query",
    "ResourceSelectionError": "resource_query",
    "canonical_request_fingerprint": "authorization",
}


class _LazyExportNames:
    def __init__(self, module_name: str, public_names: Collection[str]) -> None:
        self._module: ModuleType = modules[module_name]
        self._public_names = public_names

    def names(self) -> list[str]:
        return sorted(set(vars(self._module)) | set(self._public_names))


class _LazyRuntimeExports(_LazyExportNames):
    def __init__(self, module_name: str) -> None:
        super().__init__(module_name, _EXPORT_MODULE)

    def resolve(self, name: str) -> object:
        target = _EXPORT_MODULE.get(name)
        if target is None:
            raise AttributeError(f"module {self._module.__name__!r} has no attribute {name!r}")
        value = getattr(import_module(f".{target}", self._module.__name__), name)
        setattr(self._module, name, value)
        return value


class _LazyOwnerExports(_LazyExportNames):
    def __init__(
        self, module_name: str, exports: dict[str, tuple[str, str]], public_names: list[str]
    ) -> None:
        super().__init__(module_name, public_names)
        self._exports = exports

    def resolve(self, name: str) -> object:
        """Resolve public name from its *own* bounded context only on use."""
        source = self._exports.get(name)
        if source is None:
            raise AttributeError(name)
        module, attr = source
        return getattr(import_module(module), attr)
