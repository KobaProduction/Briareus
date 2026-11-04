from __future__ import annotations

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from fastmcp.server import create_proxy

from briareus_ghidra.settings import GhidraSettings

_private_settings = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_ghidra_settings = GhidraSettings()

mcp = build_private_mcp("ghidra", _management)
mcp.mount(
    server=create_proxy(
        _ghidra_settings.backend_url,
        name="ghidra-mcp",
        mode="auto",
    )
)

app = private_http_app(mcp, _private_settings)
