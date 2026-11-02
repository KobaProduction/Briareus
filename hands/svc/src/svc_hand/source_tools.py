"""Original provider callable families with per-effect credentials and policies."""

from pathlib import Path

from common.tool_registration import ToolRegistrar
from hand_runtime.account_lease import InvocationAccounts
from modules.github.account_views import GitHubAccountList
from modules.github.registration import register_github_tools
from modules.github.tool_context import GitHubRuntimeContext
from modules.gitlab.account_views import GitLabAccountList
from modules.gitlab.gitlab_tools import register_gitlab_tools
from modules.gitlab.models import GitLabProfile
from modules.gitlab.tool_context import GitLabRuntimeContext
from service_runtime.runtime_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL, WRITE_EXTERNAL

from .infrastructure.provider_policies import SourceProviderPolicies
from .node_git import NodeGitHubClient, NodeGitLabClient


class NodeGitHubContext(GitHubRuntimeContext):
    def list_accounts(self) -> GitHubAccountList:
        accounts = self._configured_accounts()
        return GitHubAccountList(accounts=accounts, count=len(accounts))

    def _client(self, account_id: str) -> NodeGitHubClient:
        account = self.admin_api.resolve_account(account_id, provider="github")
        client = NodeGitHubClient.from_account(account, self.policy)
        client.workspace_root = Path("/project-data")
        return client


class NodeGitLabContext(GitLabRuntimeContext):
    def accounts(self) -> GitLabAccountList:
        accounts = self._configured_accounts()
        return GitLabAccountList(accounts=accounts, count=len(accounts))

    def client(self, account_id: str) -> NodeGitLabClient:
        account = self.admin_api.resolve_account(account_id, provider="gitlab")
        profile = GitLabProfile.from_account(account)
        return NodeGitLabClient(
            profile,
            protected_branches=self.settings.protected_branches,
            workspace_root=Path("/project-data"),
        )


def register_source_tools(
    mcp: ToolRegistrar, accounts: InvocationAccounts, policies: SourceProviderPolicies | None = None
) -> tuple[NodeGitHubContext, NodeGitLabContext]:
    selected = policies if policies is not None else SourceProviderPolicies.from_context(None)
    github = NodeGitHubContext(accounts, selected.github)
    gitlab = NodeGitLabContext(accounts, selected.gitlab)
    github.runtime_policy = selected.github_runtime
    register_github_tools(mcp, github, lambda: github.runtime_policy)
    register_gitlab_tools(mcp, gitlab, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL)
    return github, gitlab
