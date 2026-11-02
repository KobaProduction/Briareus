from __future__ import annotations

from functools import partial

from common.runtime_common import admin_api_client, private_http_app
from common.settings import (
    AdminApiClientSettings,
    GitHubPolicySettings,
    PrivateRuntimeSettings,
)
from modules.project_runtime.runtime_telemetry import build_runtime_mcp
from service_runtime.runtime_policy_contracts import GitHubRuntimePolicy as GitHubRuntimePolicy
from source_control.presentation.runtime_bindings import (
    _github_runtime_policy as _read_github_runtime_policy,
)

from .registration import register_github_tools
from .tool_context import GitHubRuntimeContext
from .workflow_guard import GitHubLocalFirstMiddleware

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_policy = GitHubPolicySettings()
_context = GitHubRuntimeContext(_admin_api, _policy)

mcp, _runtime_telemetry = build_runtime_mcp("svc", name="github")


_github_runtime_policy = partial(_read_github_runtime_policy, _admin_api)


mcp.middleware.insert(0, GitHubLocalFirstMiddleware(_github_runtime_policy))

register_github_tools(mcp, _context, _github_runtime_policy)

app = _runtime_telemetry.attach(private_http_app(mcp, _private_settings))
