from __future__ import annotations

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_terminal_policy import TerminalRuntimePolicy


def terminal_runtime_policy(client: ControlPanelClient) -> TerminalRuntimePolicy:
    return client.cached_resource(
        "/internal/runtime-settings/terminal",
        cache_key=client.cache_keys.terminal_policy(),
        model=TerminalRuntimePolicy,
    )
