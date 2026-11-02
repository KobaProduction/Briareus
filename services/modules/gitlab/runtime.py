from __future__ import annotations

from functools import partial

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import admin_api_client, private_http_app
from common.runtime_policy_contracts import GitLabRuntimePolicy as GitLabRuntimePolicy
from common.settings import (
    AdminApiClientSettings,
    GitLabSettings,
    PrivateRuntimeSettings,
)
from modules.project_runtime.runtime_telemetry import build_runtime_mcp
from source_control.presentation.runtime_bindings import (
    _gitlab_runtime_policy as _read_gitlab_runtime_policy,
)

from .gitlab_tools import register_gitlab_tools
from .tool_context import GitLabRuntimeContext
from .workflow_guard import GitLabLocalFirstMiddleware

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_context = GitLabRuntimeContext(_admin_api, GitLabSettings())

mcp, _runtime_telemetry = build_runtime_mcp("svc", name="gitlab")


_gitlab_runtime_policy = partial(_read_gitlab_runtime_policy, _admin_api)


mcp.middleware.insert(0, GitLabLocalFirstMiddleware(_gitlab_runtime_policy))

register_gitlab_tools(
    mcp,
    _context,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = _runtime_telemetry.attach(private_http_app(mcp, _private_settings))
