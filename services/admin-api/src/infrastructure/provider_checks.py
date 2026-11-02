"""HTTP-only provider probes with explicit account TLS configuration."""

from __future__ import annotations

import ssl
import time
from urllib.parse import urlsplit

import httpx
import jwt
from application.provider_verification import (
    ConnectionVerification,
    CoolifyVerification,
    GitHubVerification,
    GitLabVerification,
    SigNozVerification,
)
from domain.accounts import Account, AuthType, Provider

from common.provider_identity import CoolifyTeamMetadata, SigNozReply, SigNozServiceAccount

from .provider_metadata import GitHubAppMetadata, GitHubUserMetadata, GitLabUserMetadata


class ProviderConnectionVerifier:
    def verify(self, account: Account, credential: str) -> ConnectionVerification:
        if account.provider is Provider.GITHUB:
            return self._verify_github(account, credential)
        if account.provider is Provider.GITLAB:
            return self._verify_gitlab(account, credential)
        if account.provider is Provider.SIGNOZ:
            return self._verify_signoz(account, credential)
        return self._verify_coolify(account, credential)

    @staticmethod
    def _context(account: Account) -> ssl.SSLContext | bool:
        if urlsplit(account.base_url).scheme != "https":
            return True
        if not account.verify_tls:
            return False
        if account.ca_cert_pem:
            return ssl.create_default_context(cadata=account.ca_cert_pem.replace("\\n", "\n"))
        return True

    @classmethod
    def _get(
        cls, account: Account, path: str, *, headers: dict[str, str], provider_name: str
    ) -> httpx.Response:
        parsed = urlsplit(account.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"{provider_name} base_url must be an http(s) origin")
        try:
            # Match the retained probe's redirect, proxy and TLS settings.
            with httpx.Client(
                verify=cls._context(account),
                timeout=15.0,
                follow_redirects=True,
                max_redirects=10,
                trust_env=True,
            ) as client:
                response = client.get(account.base_url.rstrip("/") + path, headers=headers)
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as exc:
            detail = exc.response.content[:2048].decode("utf-8", "replace")
            raise ValueError(
                f"{provider_name} verification failed HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ValueError(f"{provider_name} verification transport error: {exc}") from exc

    @classmethod
    def _verify_github(cls, account: Account, credential: str) -> GitHubVerification:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mcp-bridge-admin-api",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        endpoint = "/user"
        if account.auth_type is AuthType.GITHUB_APP:
            if not account.external_id.isdigit():
                raise ValueError("GitHub App external_id must be numeric APP_ID")
            now = int(time.time())
            token = jwt.encode(
                {"iat": now - 60, "exp": now + 9 * 60, "iss": account.external_id},
                credential.replace("\\n", "\n"),
                algorithm="RS256",
            )
            headers["Authorization"] = f"Bearer {token}"
            endpoint = "/app"
        elif account.auth_type is AuthType.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {credential.strip()}"
        else:
            raise ValueError("unsupported GitHub auth type")
        response = cls._get(account, endpoint, headers=headers, provider_name="GitHub")
        identity = (
            GitHubAppMetadata.model_validate_json(response.content)
            if account.auth_type is AuthType.GITHUB_APP
            else GitHubUserMetadata.model_validate_json(response.content)
        )
        return GitHubVerification(
            account=account.alias,
            auth_type=account.auth_type.value,
            app_id=account.external_id or None,
            login=identity.login if isinstance(identity, GitHubUserMetadata) else None,
            slug=identity.slug if isinstance(identity, GitHubAppMetadata) else None,
            name=identity.name,
        )

    @classmethod
    def _verify_signoz(cls, account: Account, token: str) -> SigNozVerification:
        response = cls._get(
            account,
            "/api/v1/service_accounts/me",
            provider_name="SigNoz",
            headers={
                "Accept": "application/json",
                "SIGNOZ-API-KEY": token.strip(),
                "User-Agent": "mcp-bridge-admin-api",
            },
        )
        data = SigNozReply[SigNozServiceAccount].model_validate_json(response.content)
        return SigNozVerification(
            account=account.alias, base_url=account.base_url, service_account=data
        )

    @classmethod
    def _verify_coolify(cls, account: Account, token: str) -> CoolifyVerification:
        response = cls._get(
            account,
            "/api/v1/teams/current",
            provider_name="Coolify",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token.strip()}",
                "User-Agent": "mcp-bridge-admin-api",
            },
        )
        data = CoolifyTeamMetadata.model_validate_json(response.content)
        return CoolifyVerification(account=account.alias, base_url=account.base_url, team=data)

    @classmethod
    def _verify_gitlab(cls, account: Account, token: str) -> GitLabVerification:
        headers = {"Accept": "application/json", "User-Agent": "mcp-bridge-admin-api"}
        if account.auth_type is AuthType.PRIVATE_TOKEN:
            headers["PRIVATE-TOKEN"] = token
        elif account.auth_type is AuthType.BEARER:
            headers["Authorization"] = f"Bearer {token}"
        elif account.auth_type is AuthType.JOB_TOKEN:
            headers["JOB-TOKEN"] = token
        else:
            raise ValueError("unsupported GitLab auth type")
        response = cls._get(account, "/api/v4/user", headers=headers, provider_name="GitLab")
        data = GitLabUserMetadata.model_validate_json(response.content)
        return GitLabVerification(
            account=account.alias,
            user_id=data.id,
            username=data.username,
            name=data.name,
            base_url=account.base_url,
        )
