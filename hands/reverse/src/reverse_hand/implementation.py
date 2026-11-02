"""Copied functional Hand implementation, independently packaged.

This inventory is intentionally side-effect-free: importing any legacy runtime
may initialize clients, workspaces, process managers or privileged effects.
The protected HTTP/WS transport remains denied until its authorization adapter
can verify a current Rauthy identity and Cedar AgentSession grant per effect.
"""

from __future__ import annotations

from importlib import import_module as import_module
from types import ModuleType as ModuleType

from service_runtime.source_inventory import _SourceModuleLoader

SOURCE_ASGI_ENTRYPOINT = "modules.analysis.runtime:app"
SOURCE_TOOL_MODULES = (
    "modules.analysis.reverse_owner",
    "modules.analysis.provider",
    "modules.analysis.workspace_transfer",
)


load_source_module = _SourceModuleLoader(
    SOURCE_ASGI_ENTRYPOINT, SOURCE_TOOL_MODULES
).load_source_module
