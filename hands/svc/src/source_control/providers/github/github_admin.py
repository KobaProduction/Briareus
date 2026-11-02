from __future__ import annotations

import urllib.parse

from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError
from .identity_views import ReservedBranchRepoint
from .infrastructure.schemas.repository import (
    BranchProtectionRecord,
    GitReferenceRecord,
    GitReferenceUpdate,
    RepositoryPolicyRecord,
)


def repoint_reserved_branch(
    client: GitHubActionsClient,
    repository: str,
    branch: str,
    expected_head_sha: str,
    target_sha: str,
    *,
    dry_run: bool = True,
) -> ReservedBranchRepoint:
    """Repoint a Bridge-reserved branch without changing repository content.

    This is intentionally narrower than a general force-ref primitive. The target
    commit must have the same tree as the current reserved-branch head and must
    already carry the current Agent App Git identity. The branch must be reserved
    by Bridge policy, must not be the repository default branch, and must not be
    GitHub-protected. A compare-and-swap head check is repeated immediately before
    the forced ref update.
    """
    repository = client._assert_allowed(repository)
    branch = branch.strip()
    expected_head_sha = expected_head_sha.strip()
    target_sha = target_sha.strip()
    if not branch:
        raise GitHubAgentError("branch must not be empty")
    if not expected_head_sha:
        raise GitHubAgentError("expected_head_sha is required")
    if not target_sha:
        raise GitHubAgentError("target_sha is required")
    if branch.casefold() not in client.protected_branches:
        raise GitHubAgentError(f"branch is not reserved by bridge mutation policy: {branch}")

    repo = client._repo_model(
        repository, "GET", f"/repos/{repository}", response_type=RepositoryPolicyRecord
    ).data
    default_branch = repo.default_branch
    if default_branch and branch.casefold() == default_branch.casefold():
        raise GitHubAgentError(
            f"reserved-branch admin repoint refuses the repository default branch: {branch}"
        )

    branch_q = urllib.parse.quote(branch, safe="")
    branch_info = client._repo_model(
        repository,
        "GET",
        f"/repos/{repository}/branches/{branch_q}",
        response_type=BranchProtectionRecord,
    ).data
    if branch_info.protected:
        raise GitHubAgentError(
            f"reserved branch is protected by GitHub and cannot be repointed here: {branch}"
        )

    ref = client._repo_model(
        repository,
        "GET",
        f"/repos/{repository}/git/ref/heads/{branch_q}",
        response_type=GitReferenceRecord,
    ).data
    old_head = ref.object.sha
    if old_head != expected_head_sha:
        raise GitHubAgentError(
            f"branch head changed: expected {expected_head_sha}, found {old_head}"
        )

    old_commit = client._git_commit_object(repository, old_head)
    target_commit = client._git_commit_object(repository, target_sha)
    old_tree = old_commit.tree.sha
    target_tree = target_commit.tree.sha
    if old_tree != target_tree:
        raise GitHubAgentError(
            "reserved-branch repoint would change repository content; "
            f"current_tree={old_tree}, target_tree={target_tree}"
        )

    identity = client._agent_app_identity()
    identity_name = identity.name
    identity_email = identity.email
    if not client._identity_matches(target_commit, identity_name, identity_email):
        raise GitHubAgentError(
            f"target commit does not use the current Agent App identity; target_sha={target_sha}"
        )

    result: ReservedBranchRepoint = ReservedBranchRepoint(
        repository=repository,
        branch=branch,
        old_head_sha=old_head,
        new_head_sha=target_sha,
        tree_sha=old_tree,
        content_changed=False,
        bridge_reserved=True,
        github_protected=False,
        agent_identity=identity,
        dry_run=dry_run,
        ref_updated=False,
    )
    if old_head == target_sha:
        result.status = "already_at_target"
        return result
    if dry_run:
        result.status = "ready"
        return result

    current_ref = client._repo_model(
        repository,
        "GET",
        f"/repos/{repository}/git/ref/heads/{branch_q}",
        response_type=GitReferenceRecord,
    ).data
    current_head = current_ref.object.sha
    if current_head != expected_head_sha:
        raise GitHubAgentError(
            "reserved branch changed during repoint; "
            f"expected {expected_head_sha}, found {current_head}"
        )

    client._repo_ack(
        repository,
        "PATCH",
        f"/repos/{repository}/git/refs/heads/{branch_q}",
        payload=GitReferenceUpdate(sha=target_sha, force=True),
    )
    result.ref_updated = True
    result.status = "updated"
    return result
