"""Composition entry point for the accepted identity-only graph rewrite."""

from .application.history import HistoryRewriteResult, RewriteCommand, RewriteHistory
from .domain.history import HistoryRewriteError
from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError
from .infrastructure.history import GitHubHistory


def rewrite_branch_identity_graph(
    client: GitHubActionsClient,
    repository: str,
    branch: str,
    expected_head_sha: str,
    *,
    identity_source: str = "current_agent_app",
    preserve_messages: bool = True,
    preserve_trees: bool = True,
    preserve_author_dates: bool = True,
    max_commits: int = 500,
    dry_run: bool = True,
) -> HistoryRewriteResult:
    command = RewriteCommand(
        repository,
        branch,
        expected_head_sha,
        identity_source,
        preserve_messages,
        preserve_trees,
        preserve_author_dates,
        max_commits,
        dry_run,
    )
    try:
        return RewriteHistory(GitHubHistory(client)).execute(command)
    except HistoryRewriteError as exc:
        raise GitHubAgentError(str(exc)) from exc
