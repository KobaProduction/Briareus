from __future__ import annotations

from collections.abc import Callable

from briareus_git.workflow_guard import LocalFirstMiddleware, WorkflowConfig
from briareus_gitlab_policy import GitLabRuntimePolicy

LOCAL_FIRST_GUIDANCE = (
    "Koba GitLab workflow: for substantial source changes, prefer one local-first cycle: "
    "checkout with mode='git' into the persistent Terminal workspace, edit and validate locally, "
    "commit locally, authorize the checkout, then publish once with push_local_git. "
    "Push to the requested branch if GitLab permits it; create a merge request only "
    "when repository rules require one or the user requests one. "
    "Avoid repeated per-file GitLab API mutations; issues, merge requests, notes and "
    "pipelines remain control-plane operations."
    " If Terminal Git lacks credentials, inspect GitLab accounts and call "
    "authorize_local_git(account_id, project, destination), then retry. "
    "Check connected MCP authorization before asking the user for terminal credentials."
)

REMOTE_SOURCE_MUTATION_DISABLED = (
    "Remote GitLab source/history mutations are disabled by policy. Use checkout_repository with "
    "mode='git', perform source work in Terminal, authorize_local_git, and publish with "
    "push_local_git. Issues, merge requests, notes and pipeline controls remain available."
)

LOCAL_GIT_DISABLED = (
    "Local Git transport is disabled by policy. Enable it in Version Control → GitLab → Settings "
    "before authorizing or pushing a local checkout."
)

SOURCE_MUTATION_TOOLS = frozenset(
    {
        "put_file",
        "delete_file",
        "commit_actions",
        "create_branch",
        "delete_branch",
        "create_tag",
        "delete_tag",
        "rebase_merge_request",
    }
)

LOCAL_GIT_TOOLS = frozenset({"authorize_local_git", "push_local_git"})
GUIDANCE_TOOLS = SOURCE_MUTATION_TOOLS | LOCAL_GIT_TOOLS | {"checkout_repository"}


_CONFIG = WorkflowConfig(
    provider="gitlab",
    source_mutations=SOURCE_MUTATION_TOOLS,
    local_git_tools=LOCAL_GIT_TOOLS,
    guidance_tools=GUIDANCE_TOOLS,
    guidance=LOCAL_FIRST_GUIDANCE,
    remote_denial=REMOTE_SOURCE_MUTATION_DISABLED,
    local_denial=LOCAL_GIT_DISABLED,
    checkout_description=(
        "Preferred entry point for substantial source work. Use mode='git', continue in "
        "Terminal, then authorize and push the local checkout."
    ),
    checkout_guidance=LOCAL_FIRST_GUIDANCE,
)


class GitLabLocalFirstMiddleware(LocalFirstMiddleware):
    def __init__(self, policy_provider: Callable[[], GitLabRuntimePolicy]) -> None:
        super().__init__(policy_provider, _CONFIG)
