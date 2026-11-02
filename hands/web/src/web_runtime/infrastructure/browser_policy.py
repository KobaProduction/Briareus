"""JSON boundary for the existing profile-local browser policy file."""

from __future__ import annotations

import json

from web_runtime.domain.browser_policy import BrowserPolicy


def restore_browser_policy(policy: BrowserPolicy, source: str) -> None:
    payload: object = json.loads(source)
    if not isinstance(payload, dict):
        return
    agent_access = payload.get("agent_access_enabled")
    if isinstance(agent_access, bool):
        policy.agent_access_enabled = agent_access
    developer_access = payload.get("developer_access_enabled")
    if isinstance(developer_access, bool):
        policy.developer_access_enabled = developer_access
    color_scheme = payload.get("color_scheme")
    if color_scheme in {"system", "light", "dark"}:
        if color_scheme == "system":
            policy.color_scheme = "system"
        elif color_scheme == "light":
            policy.color_scheme = "light"
        else:
            policy.color_scheme = "dark"


def encode_browser_policy(policy: BrowserPolicy) -> str:
    return json.dumps(
        {
            "agent_access_enabled": policy.agent_access_enabled,
            "developer_access_enabled": policy.developer_access_enabled,
            "color_scheme": policy.color_scheme,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
