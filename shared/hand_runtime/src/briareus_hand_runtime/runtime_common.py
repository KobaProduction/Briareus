from __future__ import annotations

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_service_catalog import ServiceDefinition, service_definition
from briareus_service_discovery import attach_service_discovery
from briareus_telemetry.observability import announce_runtime_started, build_observability
from fastmcp import FastMCP
from starlette.applications import Starlette

from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_hand_runtime.tool_observability import ToolObservabilityMiddleware


def management_client(settings: ControlPanelClientSettings) -> ControlPanelClient:
    return ControlPanelClient(settings)


def build_private_mcp(
    name: str,
    management: ControlPanelClient | None = None,
    *,
    observability_scope: str | None = None,
) -> FastMCP[None]:
    scope = observability_scope or name
    sink = build_observability(scope, management=management)
    announce_runtime_started(sink, scope)
    return FastMCP(name, middleware=[ToolObservabilityMiddleware(scope, sink)])


def private_http_app(
    mcp: FastMCP[None],
    settings: PrivateRuntimeSettings,
    *,
    service: ServiceDefinition | None = None,
) -> Starlette:
    descriptor = service or service_definition(mcp.name)
    app = mcp.http_app(
        path="/mcp",
        allowed_hosts=[*settings.http.allowed_hosts, f"{descriptor.internal_host}:*"],
        allowed_origins=list(settings.http.allowed_origins),
    )
    return attach_service_discovery(app, descriptor)
