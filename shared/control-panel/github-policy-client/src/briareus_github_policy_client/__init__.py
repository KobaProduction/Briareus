from __future__ import annotations

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_github_policy import GitHubRuntimePolicy


def github_runtime_policy(client: ControlPanelClient) -> GitHubRuntimePolicy:
    return client.cached_resource(
        "/internal/runtime-settings/github",
        cache_key=client.cache_keys.github_policy(),
        model=GitHubRuntimePolicy,
    )
