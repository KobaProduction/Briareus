"""Standalone composition of the shared infrastructure tools."""

from common.runtime_common import admin_api_client, private_http_app
from common.settings import AdminApiClientSettings, PrivateRuntimeSettings
from modules.project_runtime.runtime_telemetry import build_runtime_mcp

from .context import ObservabilityRuntimeContext
from .tools import register_observability_tools

_private = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_context = ObservabilityRuntimeContext(_admin_api)
mcp, _runtime_telemetry = build_runtime_mcp("infrastructure", name="observability")
register_observability_tools(mcp, _context)
app = _runtime_telemetry.attach(private_http_app(mcp, _private))
