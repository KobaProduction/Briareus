from __future__ import annotations

from common.admin_api_client import AdminApiClient
from common.settings import GitHubPolicySettings
from source_control.providers.github.tool_context import (
    GitHubRuntimeContext as _SharedGitHubRuntimeContext,
)

from .github_identity import GitHubPrettyIdentityClient


class GitHubRuntimeContext(_SharedGitHubRuntimeContext[GitHubPrettyIdentityClient]):
    def __init__(self, admin_api: AdminApiClient, policy: GitHubPolicySettings) -> None:
        super().__init__(admin_api, policy, client_type=GitHubPrettyIdentityClient)
