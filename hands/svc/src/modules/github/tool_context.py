from __future__ import annotations

from common.account_access import AccountAccess
from common.settings import GitHubPolicySettings
from service_runtime.runtime_policy_contracts import GitHubRuntimePolicy
from source_control.providers.github.tool_context import (
    GitHubRuntimeContext as _SharedGitHubRuntimeContext,
)

from .github_identity import GitHubPrettyIdentityClient


class GitHubRuntimeContext(_SharedGitHubRuntimeContext[GitHubPrettyIdentityClient]):
    def __init__(self, admin_api: AccountAccess, policy: GitHubPolicySettings) -> None:
        super().__init__(admin_api, policy, client_type=GitHubPrettyIdentityClient)
        self.runtime_policy = GitHubRuntimePolicy()
