from __future__ import annotations

from briareus_control_panel_client.control_panel_client import (
    AccountSelectorNotFoundError,
    ControlPanelClient,
)
from briareus_git.accounts import AccountClientCache, decorate_account, public_account
from briareus_json_values import JsonObject, JsonValue, json_array

from briareus_github.settings import GitHubPolicySettings

from .github_agent import GitHubAgentError, GitHubRequestError
from .github_identity import GitHubPrettyIdentityClient


class GitHubRuntimeContext:
    def __init__(
        self,
        management: ControlPanelClient,
        policy: GitHubPolicySettings,
    ) -> None:
        self.management = management
        self.policy = policy
        self._clients = AccountClientCache[GitHubPrettyIdentityClient]()

    def list_accounts(self) -> JsonObject:
        result = self.management.list_accounts(provider="github").to_json()
        accounts = result.get("accounts")
        if isinstance(accounts, list):
            accounts[:] = [account for account in accounts if self._visible_account(account)]
            for account in accounts:
                self._decorate_account(account)
            public = public_account(
                "github",
                "https://api.github.com",
                ["repository_read", "git_history"],
                "public-repositories-only",
            )
            public.update(
                {
                    "transport_auth": (
                        "authenticated_reader"
                        if self.policy.public_reader_account
                        else "anonymous"
                        if self.policy.public_allow_anonymous_fallback
                        else "unavailable"
                    ),
                    "reader_selector": self.policy.public_reader_account or "none",
                    "anonymous_fallback": self.policy.public_allow_anonymous_fallback,
                }
            )
            accounts.append(public)
            result["count"] = len(accounts)
        return result

    @staticmethod
    def _visible_account(account: JsonValue) -> bool:
        if not isinstance(account, dict):
            return True
        return not (
            str(account.get("alias", "")).casefold() == "authenticated"
            and str(account.get("auth_type", "")) == "github_token"
        )

    def _decorate_account(self, account: JsonValue) -> None:
        if not isinstance(account, dict):
            return
        auth_type = str(account.get("auth_type", ""))
        decorate_account(account, self._potential_capabilities(auth_type), "repository-dependent")
        if auth_type == "github_app":
            account["public_read_fallback"] = (
                bool(self.policy.public_reader_account)
                or self.policy.public_allow_anonymous_fallback
            )

    @staticmethod
    def _potential_capabilities(auth_type: str) -> list[str]:
        if auth_type == "public":
            return [
                "repository_read",
                "issues",
                "pull_requests",
                "actions",
                "checks",
                "git_history",
            ]
        capabilities = [
            "repository_read",
            "repository_write",
            "issues",
            "pull_requests",
            "reviews",
            "actions",
            "checks",
            "git_history",
        ]
        if auth_type == "github_app":
            capabilities.append("installation_scoped_access")
        else:
            capabilities.append("user_token_scoped_access")
        return capabilities

    def account_capabilities(
        self,
        account_id: str,
        repository: str = "",
    ) -> JsonObject:
        client = self._client(account_id)
        result = client.account_capabilities()
        result["potential_capabilities"] = json_array(
            self._potential_capabilities(client.auth_type),
            context="GitHub potential capabilities",
        )
        result["permission_scope"] = (
            "public-repositories-only" if client.public_only else "repository-dependent"
        )
        if repository.strip():
            target = repository.strip()
            try:
                result["repository"] = client.capabilities(target)
            except GitHubAgentError as exc:
                if client.auth_type != "github_app" or "is not installed for GitHub App" not in str(
                    exc
                ):
                    raise
                public = self._public_client()
                public._assert_public_repository(target)
                public_capabilities = public.capabilities(target)
                public_capabilities["access_mode"] = "public_read_fallback"
                result["repository"] = public_capabilities
        return result

    def _public_reader_selector(self) -> str:
        configured = self.policy.public_reader_account.strip()
        if configured:
            return configured
        if self.policy.public_allow_anonymous_fallback:
            return ""
        raise GitHubAgentError(
            "GitHub public read-only access is disabled; set "
            "GITHUB_PUBLIC_ALLOW_ANONYMOUS_FALLBACK=true or provide "
            "GITHUB_PUBLIC_READER_ACCOUNT explicitly"
        )

    def _public_client(self) -> GitHubPrettyIdentityClient:
        selector = self._public_reader_selector()
        if not selector:
            return GitHubPrettyIdentityClient(
                account_id="public",
                auth_type="public",
                public_only=True,
                public_reader_account="",
                workspace_root=self.policy.workspace_root,
                protected_branches=self.policy.protected_branches,
                required_checks=self.policy.required_checks,
                required_reviewers=self.policy.required_reviewers,
            )
        account = self.management.resolve_account(selector, provider="github")
        if not account.enabled:
            raise GitHubAgentError(f"GitHub public reader account is disabled: {selector}")
        if account.auth_type != "github_token":
            raise GitHubAgentError(
                "GITHUB_PUBLIC_READER_ACCOUNT must reference a github_token account; "
                "GitHub App installation tokens cannot read arbitrary repositories outside "
                "their installation scope"
            )

        def build() -> GitHubPrettyIdentityClient:
            credential = account.credential.replace("\\n", "\n").strip()
            if not credential:
                raise GitHubAgentError("GitHub public reader account has no credential")
            return GitHubPrettyIdentityClient(
                account_id="public",
                token=credential,
                auth_type="public",
                public_only=True,
                public_reader_account=account.alias or account.id,
                workspace_root=self.policy.workspace_root,
                protected_branches=self.policy.protected_branches,
                required_checks=self.policy.required_checks,
                required_reviewers=self.policy.required_reviewers,
            )

        return self._clients.get("public", account.id, account.updated_at, build)

    def _client(self, account_id: str) -> GitHubPrettyIdentityClient:
        selector = account_id.strip().casefold()
        if selector in {"public", "anonymous"}:
            return self._public_client()
        try:
            account = self.management.resolve_account(account_id, provider="github")
        except AccountSelectorNotFoundError as exc:
            raise GitHubRequestError(str(exc)) from exc

        def build() -> GitHubPrettyIdentityClient:
            client = GitHubPrettyIdentityClient.from_account(account, self.policy)
            if account.auth_type == "github_app":
                client.public_read_client = self._public_client
            return client

        return self._clients.get("github", account.id, account.updated_at, build)

    def client(self, account_id: str) -> GitHubPrettyIdentityClient:
        return self._client(account_id)

    def clear(self) -> None:
        self._clients.clear()
