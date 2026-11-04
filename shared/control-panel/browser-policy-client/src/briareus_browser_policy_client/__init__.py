from __future__ import annotations

from briareus_browser_policy import BrowserLauncherPolicy, BrowserRuntimePolicy
from briareus_control_panel_client.control_panel_client import ControlPanelClient


def browser_runtime_policy(client: ControlPanelClient) -> BrowserRuntimePolicy:
    return client.cached_resource(
        "/internal/runtime-settings/browser",
        cache_key=client.cache_keys.browser_policy(),
        model=BrowserRuntimePolicy,
    )


def browser_launcher_policy(client: ControlPanelClient) -> BrowserLauncherPolicy:
    return BrowserLauncherPolicy.model_validate(
        client.request("GET", "/internal/runtime-settings/browser-launcher")
    )
