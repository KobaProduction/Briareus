from __future__ import annotations

from collections.abc import Callable

from briareus_git.workflow_guard import LocalFirstMiddleware, WorkflowConfig
from briareus_github_policy import GitHubRuntimePolicy

LOCAL_FIRST_GUIDANCE = (
    "Koba GitHub workflow: for substantial source changes, prefer one local-first cycle: "
    "checkout/clone into the persistent Terminal workspace, edit and test locally, create local "
    "commits as needed, then publish once with an authenticated Git push or one batched atomic "
    "GitHub commit. Push to the requested branch if GitHub permits it; create a PR only when "
    "repository rules require one or the user requests one. Avoid repeated GitHub API mutations; "
    "they waste API quota and fragment history."
    " If Terminal Git lacks credentials, inspect accounts and call "
    "authorize_local_git(account_id, repository, destination), then retry. "
    "Check connected MCP authorization before asking the user for terminal credentials."
)

REMOTE_SOURCE_MUTATION_DISABLED = (
    "Remote GitHub source/history mutations are disabled by policy. Use checkout_repository "
    "with mode='git', perform source work in Terminal, and publish through the configured Git "
    "transport. Use authorize_local_git to connect the selected MCP account to "
    "Terminal Git. PR/review/issues/Actions control-plane tools remain available."
)

# These operations mutate repository source/history directly. Control-plane mutations such as
# creating PRs, comments, reviews, issues and Actions operations deliberately remain available.
SOURCE_MUTATION_TOOLS = frozenset(
    {
        "create_branch",
        "put_file",
        "delete_file",
        "copy_files",
        "commit_files",
        "delete_branch",
        "rename_branch",
        "reset_branch",
        "create_tag",
        "delete_tag",
        "fast_forward",
        "merge_branch",
        "update_pull_branch",
        "rewrite_branch_identity",
        "rewrite_branch_identity_graph",
        "repoint_reserved_branch",
    }
)

GUIDANCE_TOOLS = SOURCE_MUTATION_TOOLS | {"checkout_repository"}


LOCAL_GIT_TOOLS = frozenset({"authorize_local_git", "push_local_git"})
LOCAL_GIT_DISABLED = (
    "Local Git transport is disabled in application settings; enable it after review."
)

_CONFIG = WorkflowConfig(
    provider="github",
    source_mutations=SOURCE_MUTATION_TOOLS,
    local_git_tools=LOCAL_GIT_TOOLS,
    guidance_tools=GUIDANCE_TOOLS,
    guidance=LOCAL_FIRST_GUIDANCE,
    remote_denial=REMOTE_SOURCE_MUTATION_DISABLED,
    local_denial=LOCAL_GIT_DISABLED,
    checkout_description=(
        "Preferred entry point for substantial source work. Checkout with mode='git', "
        "continue in the persistent Terminal workspace, and publish once after validation."
    ),
    checkout_guidance=(
        "Local-first workflow selected. Continue substantial edits/tests in Terminal "
        "and publish once."
    ),
    report_local_transport=False,
)


class GitHubLocalFirstMiddleware(LocalFirstMiddleware):
    def __init__(self, policy_provider: Callable[[], GitHubRuntimePolicy]) -> None:
        super().__init__(policy_provider, _CONFIG)
