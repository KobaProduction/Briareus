"""Original provider callable families with per-effect credentials and policies."""
from pathlib import Path
from common.runtime_annotations import READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL
from common.runtime_policy_contracts import GitHubRuntimePolicy, GitLabRuntimePolicy
from common.settings import GitHubPolicySettings, GitLabSettings
from modules.github.registration import register_github_tools
from modules.github.tool_context import GitHubRuntimeContext
from modules.gitlab.gitlab_tools import register_gitlab_tools
from modules.gitlab.tool_context import GitLabRuntimeContext
from modules.gitlab.models import GitLabProfile
from .node_git import NodeGitHubClient, NodeGitLabClient


class NodeGitHubContext(GitHubRuntimeContext):
    def list_accounts(self):
        return self.admin_api.list_accounts(provider="github").to_json()

    def _client(self, account_id):
        account = self.admin_api.resolve_account(account_id, provider="github")
        client = NodeGitHubClient.from_account(account, self.policy)
        client.workspace_root = Path("/project-data")
        return client


class NodeGitLabContext(GitLabRuntimeContext):
    def accounts(self):
        return self.admin_api.list_accounts(provider="gitlab").to_json()

    def client(self, account_id):
        account = self.admin_api.resolve_account(account_id, provider="gitlab")
        profile = GitLabProfile(account_id=account.id, alias=account.alias,
            base_url=account.base_url, auth_type=account.auth_type,
            verify_tls=account.verify_tls, ca_cert_pem=account.ca_cert_pem or "")
        profile.bind_token(account.credential)
        return NodeGitLabClient(profile, protected_branches=self.settings.protected_branches,
                                workspace_root=Path("/project-data"))


def register_source_tools(mcp, accounts, policies=None):
    policies = policies or {}
    github = NodeGitHubContext(accounts, GitHubPolicySettings.model_validate(policies.get("github", {})))
    gitlab = NodeGitLabContext(accounts, GitLabSettings.model_validate(policies.get("gitlab", {})))
    github_policy = GitHubRuntimePolicy.model_validate(policies.get("github_runtime", {}))
    gitlab_policy = GitLabRuntimePolicy.model_validate(policies.get("gitlab_runtime", {}))
    github.runtime_policy = github_policy
    register_github_tools(mcp, github, lambda: github.runtime_policy)
    register_gitlab_tools(mcp, gitlab, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL)
    return github, gitlab
