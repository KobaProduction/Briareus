from __future__ import annotations

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_mcp_policy import McpRuntimePolicy


def mcp_runtime_policy(client: ControlPanelClient) -> McpRuntimePolicy:
    return client.cached_resource(
        "/internal/runtime-settings/mcp",
        cache_key=client.cache_keys.mcp_policy(),
        model=McpRuntimePolicy,
    )
