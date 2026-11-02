from __future__ import annotations

import threading

from service_runtime.owner_settings import GitLabSettings
from source_control.providers.github.contracts import AccountAccess

from .account_views import GitLabAccountList, GitLabAccountView
from .models import GitLabProfile
from .project_views import GitLabAccountCapabilities
from .projects import GitLabProjectClient


class GitLabRuntimeContext[ClientT: GitLabProjectClient, AccountSourceT: AccountAccess]:
    client_type: type[ClientT]

    def __init__(
        self,
        admin_api: AccountSourceT,
        settings: GitLabSettings,
    ) -> None:
        self.admin_api = admin_api
        self.settings = settings
        self._lock = threading.Lock()
        self._client_cache: dict[str, tuple[str, ClientT]] = {}

    def _configured_accounts(self) -> list[GitLabAccountView]:
        configured = self.admin_api.list_accounts(provider="gitlab")
        return [
            GitLabAccountView.from_account(
                account,
                potential_capabilities=self._potential_capabilities(account.auth_type),
                permission_scope="project-dependent",
            )
            for account in configured.accounts
        ]

    def accounts(self) -> GitLabAccountList:
        accounts = self._configured_accounts()
        accounts.append(
            GitLabAccountView(
                id="public",
                alias="public",
                provider="gitlab",
                auth_type="public",
                base_url="https://gitlab.com",
                created_at="",
                updated_at="",
                potential_capabilities=["project_read", "repository_read"],
                permission_scope="public-projects-only",
                preferred_selector="public",
            )
        )
        return GitLabAccountList(accounts=accounts, count=len(accounts))

    @staticmethod
    def _potential_capabilities(auth_type: str) -> list[str]:
        if auth_type == "public":
            return ["project_read", "repository_read"]
        capabilities = [
            "project_read",
            "repository_read",
            "repository_write",
            "issues",
            "merge_requests",
            "pipelines",
        ]
        if auth_type == "job_token":
            capabilities.append("job_token_scoped_access")
        elif auth_type == "private_token":
            capabilities.append("personal_access_token_scoped_access")
        else:
            capabilities.append("oauth_bearer_scoped_access")
        return capabilities

    def account_capabilities(
        self,
        account_id: str,
        project: str = "",
    ) -> GitLabAccountCapabilities:
        client = self.client(account_id)
        result = client.account_capabilities(project.strip())
        auth_type = "public" if client.anonymous_only else client.profile.auth_type
        result.potential_capabilities = self._potential_capabilities(auth_type)
        result.permission_scope = (
            "public-projects-only" if client.anonymous_only else "project-dependent"
        )
        return result

    def client(self, account_id: str) -> ClientT:
        selector = account_id.strip().casefold()
        if selector in {"public", "anonymous"}:
            profile = GitLabProfile(
                account_id="public",
                alias="public",
                base_url="https://gitlab.com",
                auth_type="private_token",
            )
            return self.client_type(
                profile,
                protected_branches=self.settings.protected_branches,
                anonymous_only=True,
            )
        account = self.admin_api.resolve_account(account_id, provider="gitlab")
        with self._lock:
            cached = self._client_cache.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            profile = GitLabProfile.from_account(account)
            client = self.client_type(
                profile,
                protected_branches=self.settings.protected_branches,
            )
            self._client_cache[account.id] = (account.updated_at, client)
            return client

    def clear(self) -> None:
        with self._lock:
            self._client_cache.clear()
