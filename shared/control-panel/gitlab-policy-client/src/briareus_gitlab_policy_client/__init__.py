from __future__ import annotations

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_gitlab_policy import GitLabRuntimePolicy


def gitlab_runtime_policy(client: ControlPanelClient) -> GitLabRuntimePolicy:
    return client.cached_resource(
        "/internal/runtime-settings/gitlab",
        cache_key=client.cache_keys.gitlab_policy(),
        model=GitLabRuntimePolicy,
    )
