from __future__ import annotations

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_gitlab_policy import GitLabRuntimePolicy
from briareus_gitlab_policy_client import gitlab_runtime_policy
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_tool_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL, WRITE_EXTERNAL

from briareus_gitlab.settings import GitLabSettings

from .gitlab_tools import register_gitlab_tools
from .tool_context import GitLabRuntimeContext
from .workflow_guard import GitLabLocalFirstMiddleware

_private_settings = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_context = GitLabRuntimeContext(_management, GitLabSettings())

mcp = build_private_mcp("gitlab", _management)


def _gitlab_runtime_policy() -> GitLabRuntimePolicy:
    try:
        return gitlab_runtime_policy(_management)
    except Exception:
        return GitLabRuntimePolicy()


mcp.middleware.insert(0, GitLabLocalFirstMiddleware(_gitlab_runtime_policy))

register_gitlab_tools(
    mcp,
    _context,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
