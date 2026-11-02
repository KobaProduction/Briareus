"""Source inventory allowlist loader without importing Hand implementations."""

from importlib import import_module
from types import ModuleType


class _SourceModuleLoader:
    def __init__(self, entrypoint: str, tool_modules: tuple[str, ...]) -> None:
        self._allowed = (entrypoint.partition(":")[0], *tool_modules)

    def load_source_module(self, name: str) -> ModuleType:
        """Return an explicitly packaged source module for a trusted adapter.

        This function is deliberately not reachable from the network. Calling it
        never confers permission to execute a registered tool.
        """
        if name not in self._allowed:
            raise ValueError("module is not in this Hand's source inventory")
        return import_module(name)
