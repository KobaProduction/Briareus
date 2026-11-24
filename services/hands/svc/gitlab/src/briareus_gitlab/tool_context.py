from __future__ import annotations

from briareus_control_panel_client.control_panel_client import (
    AccountSelectorNotFoundError,
    ControlPanelClient,
)
from briareus_git.accounts import AccountClientCache, decorate_account, public_account
from briareus_json_values import JsonObject, json_array

from briareus_gitlab.settings import GitLabSettings

from .errors import GitLabRequestError
from .gitlab_client import GitLabClient
from .models import GitLabProfile


class GitLabRuntimeContext:
    def __init__(
        self,
        management: ControlPanelClient,
        settings: GitLabSettings,
    ) -> None:
        self.management = management
        self.settings = settings
        self._clients = AccountClientCache[GitLabClient]()

    def accounts(self) -> JsonObject:
        result = self.management.list_accounts(provider="gitlab").to_json()
        accounts = result.get("accounts")
        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                decorate_account(
                    account,
                    self._potential_capabilities(str(account.get("auth_type", ""))),
                    "project-dependent",
                )
            accounts.append(
                public_account(
                    "gitlab",
                    "https://gitlab.com",
                    ["project_read", "repository_read"],
                    "public-projects-only",
                )
            )
            result["count"] = len(accounts)
        return result

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
            "reviews",
            "checks",
            "repository_tags",
            "job_artifacts",
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
    ) -> JsonObject:
        client = self.client(account_id)
        result = client.account_capabilities(project.strip())
        auth_type = "public" if client.anonymous_only else client.profile.auth_type
        result["potential_capabilities"] = json_array(
            self._potential_capabilities(auth_type),
            context="GitLab potential capabilities",
        )
        result["permission_scope"] = (
            "public-projects-only" if client.anonymous_only else "project-dependent"
        )
        return result

    def client(self, account_id: str) -> GitLabClient:
        selector = account_id.strip().casefold()
        if selector in {"public", "anonymous"}:
            profile = GitLabProfile(
                account_id="public",
                alias="public",
                base_url="https://gitlab.com",
                auth_type="private_token",
            )
            return GitLabClient(
                profile,
                workspace_root=self.settings.workspace_root,
                protected_branches=self.settings.protected_branches,
                anonymous_only=True,
            )
        try:
            account = self.management.resolve_account(account_id, provider="gitlab")
        except AccountSelectorNotFoundError as exc:
            raise GitLabRequestError(str(exc)) from exc

        def build() -> GitLabClient:
            profile = GitLabProfile.model_validate(
                {
                    "account_id": account.id,
                    "alias": account.alias,
                    "base_url": account.base_url,
                    "auth_type": account.auth_type,
                    "verify_tls": account.verify_tls,
                    "ca_cert_pem": account.ca_cert_pem or "",
                }
            )
            profile.bind_token(account.credential)
            return GitLabClient(
                profile,
                workspace_root=self.settings.workspace_root,
                protected_branches=self.settings.protected_branches,
            )

        return self._clients.get("gitlab", account.id, account.updated_at, build)

    def clear(self) -> None:
        self._clients.clear()
