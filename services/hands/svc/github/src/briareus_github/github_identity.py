from __future__ import annotations

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from briareus_account_contracts import ResolvedAccount
from briareus_git.local_transport import (
    LocalGitConfig,
    authorize_checkout,
    git_output,
    local_git_path,
    push_checkout,
)
from briareus_json_values import (
    JsonContainer,
    JsonObject,
    json_int,
    json_member_object,
    json_object,
    json_str,
    json_value,
)

from briareus_github.settings import GitHubPolicySettings

from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError, GitHubRequestError

_GITHUB_API = "https://api.github.com"
_LOCAL_GIT = LocalGitConfig(
    "GitHub",
    "repository",
    "koba-credentials",
    "# koba-managed-local-git-guard",
    GitHubAgentError,
    GitHubRequestError,
)


class GitHubPrettyIdentityClient(GitHubActionsClient):
    @classmethod
    def from_account(
        cls,
        account: ResolvedAccount,
        policy: GitHubPolicySettings,
    ) -> GitHubPrettyIdentityClient:
        credential = account.credential.replace("\\n", "\n").strip()
        if not credential:
            raise GitHubAgentError("GitHub account has no credential")
        if account.auth_type == "github_token":
            return cls(
                account_id=account.id,
                token=credential,
                auth_type=account.auth_type,
                workspace_root=policy.workspace_root,
                protected_branches=policy.protected_branches,
                required_checks=policy.required_checks,
                required_reviewers=policy.required_reviewers,
            )
        app_id = (account.external_id or "").strip()
        if not app_id:
            raise GitHubAgentError("GitHub App account has no APP_ID")
        return cls(
            app_id=app_id,
            private_key=credential,
            account_id=account.id,
            auth_type=account.auth_type,
            workspace_root=policy.workspace_root,
            protected_branches=policy.protected_branches,
            required_checks=policy.required_checks,
            required_reviewers=policy.required_reviewers,
        )

    """Use the GitHub App display name for Git-authored objects.

    GitHub still exposes the immutable App actor login (for example
    ``koba-ai-agent[bot]``). Direct Git objects created by the bridge use the
    human-friendly GitHub App name as ``author.name``/``committer.name`` while
    retaining the GitHub-generated bot noreply email for stable attribution.
    """

    def _app_identity(self) -> JsonObject:
        if self.public_only:
            return {
                "source": "public_authenticated_reader" if self.token else "public_anonymous",
                "display_name": "public",
                "login": "public",
                "id": 0,
                "type": "Public",
                "name": "public",
                "email": "",
                "reader_account": self.public_reader_account,
                "transport_authenticated": bool(self.token),
            }
        cached = getattr(self, "_app_identity_cache", None)
        if isinstance(cached, dict):
            return dict(cached)

        if self.token:
            return self._token_identity()

        _, app = self._request(
            "GET",
            f"{_GITHUB_API}/app",
            token=self._app_jwt(),
            auth_mode="github_app_jwt",
        )
        if not isinstance(app, dict):
            raise GitHubAgentError("unexpected GitHub App response")

        slug = json_str(app.get("slug")).strip()
        display_name = json_str(app.get("name")).strip()
        if not slug:
            raise GitHubAgentError("GitHub App response has no slug")
        if not display_name:
            display_name = slug

        login = f"{slug}[bot]"
        _, bot = self._request(
            "GET",
            f"{_GITHUB_API}/users/{urllib.parse.quote(login, safe='')}",
            token=self._any_installation_token(),
            auth_mode="installation",
        )
        if not isinstance(bot, dict):
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        try:
            bot_id = json_int(bot.get("id"), field="bot.id")
        except ValueError as exc:
            raise GitHubAgentError("unable to resolve GitHub App bot identity") from exc
        if bot_id <= 0:
            raise GitHubAgentError("unable to resolve GitHub App bot identity")
        app_identity: JsonObject = {
            "source": "current_agent_app",
            "app_id": self.app_id,
            "slug": slug,
            "display_name": display_name,
            "login": login,
            "id": bot_id,
            "type": json_str(bot.get("type"), default="Bot") or "Bot",
            "name": display_name,
            "email": f"{bot_id}+{login}@users.noreply.github.com",
        }
        self._app_identity_cache = dict(app_identity)
        return app_identity

    def _token_identity(self) -> JsonObject:
        _, app = self._request(
            "GET",
            f"{_GITHUB_API}/user",
            token=self.token,
            auth_mode="user_token",
        )
        if not isinstance(app, dict):
            raise GitHubAgentError("unexpected GitHub user response")
        login = json_str(app.get("login")).strip()
        if not login:
            raise GitHubAgentError("GitHub user response has no login")
        display_name = json_str(app.get("name")).strip() or login
        user_id = json_int(app.get("id"))
        email = json_str(app.get("email")).strip() or (
            f"{user_id}+{login}@users.noreply.github.com"
        )
        token_identity: JsonObject = {
            "source": "github_token",
            "display_name": display_name,
            "login": login,
            "id": user_id,
            "type": json_str(app.get("type"), default="User") or "User",
            "name": display_name,
            "email": email,
        }
        self._app_identity_cache = dict(token_identity)
        return token_identity

    def _agent_app_identity(self) -> JsonObject:
        """Compatibility hook used by history/admin policy code."""
        return self._app_identity()

    def _git_signature(self) -> dict[str, str]:
        identity = self._app_identity()
        return {
            "name": str(identity["name"]),
            "email": str(identity["email"]),
        }

    def _local_git_path(self, destination: str) -> Path:
        return local_git_path(self.workspace_root, destination, _LOCAL_GIT)

    @staticmethod
    def _git_output(target: Path, *args: str, env: dict[str, str] | None = None) -> str:
        return git_output(target, *args, config=_LOCAL_GIT, env=env)

    def _git_optional_output(self, target: Path, *args: str) -> str:
        return git_output(target, *args, config=_LOCAL_GIT, optional=True)

    @staticmethod
    def _expected_remote(repository: str) -> str:
        return f"https://github.com/{repository}.git"

    def _credential_url(self, repository: str) -> str:
        token = self.token
        if not token:
            installation_id = self._installation_id(repository)
            with self._credential_lock:
                self._tokens.pop(installation_id, None)
            token = self._installation_token_for_id(installation_id)
        quoted_token = urllib.parse.quote(token, safe="")
        return f"https://x-access-token:{quoted_token}@github.com/{repository}.git"

    def authorize_local_git(
        self, repository: str, destination: str, *, remote: str = "origin"
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise GitHubAgentError(
                "local Git write authorization requires an authenticated GitHub account"
            )
        expected = self._expected_remote(repository)
        return authorize_checkout(
            self,
            _LOCAL_GIT,
            repository,
            destination,
            account_id=self.account_id,
            remote=remote,
            expected=expected,
            accepted=frozenset(
                {
                    expected.removesuffix(".git"),
                    f"ssh://git@github.com/{repository}",
                    f"git@github.com:{repository}",
                }
            ),
            signature=self._git_signature,
            credential_url=lambda: self._credential_url(repository),
        )

    def push_local_git(
        self,
        repository: str,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise GitHubAgentError("local Git push requires an authenticated GitHub account")
        result = push_checkout(
            self,
            _LOCAL_GIT,
            repository,
            destination,
            account_id=self.account_id,
            branch=branch,
            remote=remote,
            set_upstream=set_upstream,
            expected=GitHubPrettyIdentityClient._expected_remote(repository),
            branch_guard=lambda name: self._assert_branch_mutation_allowed(repository, name),
        )
        result["credential_storage"] = "none"
        return result

    @staticmethod
    def _copy_payload(payload: object | None) -> JsonObject | None:
        if payload is None:
            return None
        try:
            return json_object(payload, context="GitHub request payload")
        except ValueError as exc:
            raise GitHubAgentError("GitHub request payload must be JSON-compatible") from exc

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]:
        updated = self._copy_payload(payload)
        contents_prefix = f"/repos/{repository}/contents/"
        commit_path = f"/repos/{repository}/git/commits"
        tag_path = f"/repos/{repository}/git/tags"
        is_direct_commit = updated is not None and (
            (method in {"PUT", "DELETE"} and path.startswith(contents_prefix))
            or (method == "POST" and path == commit_path)
        )

        if updated is not None and is_direct_commit:
            signature = json_value(
                self._git_signature(),
                context="GitHub git signature",
            )
            updated.setdefault("author", signature)
            updated.setdefault("committer", signature)
        elif updated is not None and method == "POST" and path == tag_path:
            updated.setdefault(
                "tagger",
                json_value(
                    self._git_signature(),
                    context="GitHub tagger signature",
                ),
            )

        return super()._repo_request(
            repository,
            method,
            path,
            payload=updated if updated is not None else payload,
            allowed_errors=allowed_errors,
        )

    def _creation_owner_installation(self, owner: str) -> tuple[str, int]:
        for account_type, route in (("User", "users"), ("Organization", "orgs")):
            status, raw = self._request(
                "GET",
                f"{_GITHUB_API}/{route}/{urllib.parse.quote(owner, safe='')}/installation",
                token=self._app_jwt(),
                allowed_errors={404},
                auth_mode="github_app_jwt",
            )
            if status == 404:
                continue
            installation = json_object(raw, context="GitHub owner installation")
            account = json_member_object(installation, "account", required=True)
            if (
                json_str(account.get("login")).casefold() != owner.casefold()
                or json_str(account.get("type")) != account_type
            ):
                raise GitHubAgentError("GitHub installation owner does not match selected owner")
            installation_id = json_int(installation.get("id"))
            if installation_id <= 0:
                raise GitHubAgentError("GitHub returned invalid owner installation id")
            return account_type, installation_id
        raise GitHubAgentError(f"GitHub App has no installation for owner {owner!r}")

    def _repository_creation_target(self, owner: str) -> tuple[str, str, str]:
        if self.token:
            identity = self._token_identity()
            owner_type = (
                "User"
                if str(identity.get("login", "")).casefold() == owner.casefold()
                else "Organization"
            )
            token, auth_mode = self.token, "user_token"
        else:
            owner_type, installation_id = self._creation_owner_installation(owner)
            token = self._installation_token_for_id(installation_id)
            auth_mode = "installation"
        endpoint = (
            "/user/repos"
            if owner_type == "User"
            else f"/orgs/{urllib.parse.quote(owner, safe='')}/repos"
        )
        return endpoint, token, auth_mode

    def create_repository(
        self,
        owner: str,
        name: str,
        *,
        private: bool = True,
        description: str = "",
        auto_init: bool = False,
    ) -> JsonObject:
        """Create a repository in the explicitly selected user/organization account."""
        owner = owner.strip()
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner):
            raise GitHubRequestError("owner must be a valid GitHub account login")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name) or name in {".", ".."}:
            raise GitHubRequestError("name must be a valid repository name without slashes")
        if self.public_only:
            raise GitHubRequestError("public GitHub access cannot create repositories")

        endpoint, token, auth_mode = self._repository_creation_target(owner)
        status, raw_created = self._request(
            "POST",
            f"{_GITHUB_API}{endpoint}",
            token=token,
            payload={
                "name": name,
                "private": private,
                "description": description,
                "auto_init": auto_init,
            },
            auth_mode=auth_mode,
        )
        created = json_object(raw_created, context="GitHub created repository")
        returned_owner = json_member_object(created, "owner", required=True)
        if (
            status != 201
            or json_str(returned_owner.get("login")).casefold() != owner.casefold()
            or json_str(created.get("name")).casefold() != name.casefold()
            or created.get("private") is not private
        ):
            raise GitHubAgentError(
                "GitHub creation response did not match requested owner/name/visibility; "
                "inspect the remote repository before retrying"
            )
        return {
            "created": True,
            "account_id": self.account_id,
            "full_name": created.get("full_name"),
            "url": created.get("html_url"),
            "private": created["private"],
            "default_branch": created.get("default_branch"),
            "id": created.get("id"),
        }

    def account_capabilities(self) -> JsonObject:
        """Return provider-reported account permissions without requiring a repository."""
        if self.public_only:
            return {
                "account_id": "public",
                "auth_type": "public",
                "identity": {"login": "public", "type": "Public"},
                "provider_permissions": {"contents": "read"},
                "provider_permissions_known": True,
                "transport_auth": "authenticated_reader" if self.token else "anonymous",
                "reader_account": self.public_reader_account,
                "note": (
                    "Authenticated public GitHub access; read-only."
                    if self.token
                    else "Anonymous public GitHub access; read-only."
                ),
            }
        if self.token:
            _, user = self._request(
                "GET",
                f"{_GITHUB_API}/user",
                token=self.token,
                auth_mode="user_token",
            )
            payload = json_object(user, context="GitHub user response")
            return {
                "account_id": self.account_id,
                "auth_type": self.auth_type,
                "identity": {
                    "login": json_str(payload.get("login")),
                    "name": json_str(payload.get("name")),
                    "type": json_str(payload.get("type")),
                },
                "provider_permissions": {},
                "provider_permissions_known": False,
                "note": (
                    "GitHub user tokens do not expose one reliable account-global permission map; "
                    "effective rights are repository/resource dependent."
                ),
            }

        _, app = self._request(
            "GET",
            f"{_GITHUB_API}/app",
            token=self._app_jwt(),
            auth_mode="github_app_jwt",
        )
        payload = json_object(app, context="GitHub App response")
        permissions = json_member_object(payload, "permissions")
        return {
            "account_id": self.account_id,
            "auth_type": self.auth_type,
            "identity": {
                "app_id": self.app_id,
                "slug": json_str(payload.get("slug")),
                "name": json_str(payload.get("name")),
            },
            "provider_permissions": {key: json_str(value) for key, value in permissions.items()},
            "provider_permissions_known": True,
            "note": (
                "GitHub App permissions are the application ceiling; installation/repository "
                "selection can further reduce effective rights."
            ),
        }

    def list_repositories(self) -> JsonObject:
        if self.public_only:
            return {
                "auth_type": "public",
                "count": 0,
                "repositories": [],
                "note": "Public selector addresses repositories explicitly by owner/name.",
                "app_identity": self._app_identity(),
            }
        base_list = super().list_repositories
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="github-list",
        ) as pool:
            repositories_future = pool.submit(base_list)
            identity_future = pool.submit(self._app_identity)
            result = repositories_future.result()
            result["app_identity"] = identity_future.result()
            return result

    def status(self, repository: str) -> JsonObject:
        base_status = super().status
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="github-status",
        ) as pool:
            status_future = pool.submit(base_status, repository)
            identity_future = pool.submit(self._app_identity)
            result = status_future.result()
            result["app_identity"] = identity_future.result()
            return result
