from __future__ import annotations

from pathlib import Path

from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_github_policy import GitHubRuntimePolicy
from briareus_github_policy_client import github_runtime_policy
from briareus_hand_runtime.hand_workflows import hand_version, register_hand_workflow
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_tool_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL, WRITE_EXTERNAL

from briareus_github.settings import GitHubPolicySettings

from .account_tools import register_github_account_tools
from .github_actions_tools import register_github_actions_tools
from .github_collab_tools import register_github_collab_tools
from .github_core_tools import register_github_core_tools
from .github_review_tools import register_github_review_tools
from .github_reviewer_tools import register_github_reviewer_tools
from .github_tools import register_github_workflow_tools
from .tool_context import GitHubRuntimeContext
from .workflow_guard import GitHubLocalFirstMiddleware

_private_settings = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_policy = GitHubPolicySettings()
_context = GitHubRuntimeContext(_management, _policy)

_source_root = Path(__file__).resolve().parent
mcp = build_private_mcp(
    "github",
    _management,
    instructions=(
        "Use skill://github-repository-workflow/SKILL.md for repository discovery, "
        "checkout, review and publishing. Check accounts and existing Server projects first. "
        "Prefer direct push to main when permitted; use PR only on confirmed block or request. "
        "Use canonical projects/<repo>, never projects/<task>/repo."
    ),
    version=hand_version(_source_root, shared_publishing=True),
)
register_hand_workflow(mcp, _source_root, "github-repository-workflow", shared_publishing=True)


def _github_runtime_policy() -> GitHubRuntimePolicy:
    try:
        return github_runtime_policy(_management)
    except Exception:
        return GitHubRuntimePolicy()


mcp.middleware.insert(0, GitHubLocalFirstMiddleware(_github_runtime_policy))

register_github_account_tools(
    mcp,
    _context.list_accounts,
    _context.account_capabilities,
    READ_EXTERNAL,
)
register_github_core_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
    _github_runtime_policy,
)
register_github_workflow_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_review_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_collab_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_actions_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_reviewer_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
