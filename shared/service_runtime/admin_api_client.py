from __future__ import annotations

import urllib.parse

from opentelemetry import trace
from pydantic import BaseModel

from .account_contracts import (
    AccountList,
    AuthenticatedReaderView,
    GitHubAuthenticatedReaderSync,
    InvocationEvent,
    InvocationEventBatch,
    ResolvedAccount,
)
from .cache import SharedCache
from .cache_contracts import CacheBackend, CacheKeys
from .http_transport import HttpTransportError, PooledHttpTransport, _HttpConnectionFactory
from .oauth_session_contracts import OAuthSessionEvent
from .runtime_policy_contracts import (
    BrowserLauncherPolicy,
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)
from .settings import AdminApiClientSettings, ValkeySettings


class AdminApiClientError(RuntimeError):
    pass


class AdminApiAcknowledgement(BaseModel):
    """Successful no-content Admin API response; no authority is inferred from it."""


_TRACER = trace.get_tracer("mcp-bridge.admin-api-client")


class AdminApiClient(_HttpConnectionFactory):
    def __init__(
        self,
        settings: AdminApiClientSettings,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
    ) -> None:
        self.url = settings.url.rstrip("/")
        self.service_token = settings.service_token
        self.timeout_seconds = settings.timeout_seconds
        if not self.url:
            raise ValueError("ADMIN_API_URL is required")
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache = cache or SharedCache(self.cache_settings)
        self.cache_keys = CacheKeys(self.cache)
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("ADMIN_API_URL must be an absolute HTTP(S) URL")
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._transport = PooledHttpTransport(
            self._new_connection,
            max_connections=8,
            acquire_timeout=self.timeout_seconds,
            span_name="admin-api.http",
        )

    def _target(self, path: str, query: dict[str, str] | None = None) -> str:
        if not path.startswith("/"):
            raise ValueError("admin-api path must start with /")
        target = self._base_path + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        return target

    def _request[T: BaseModel](
        self,
        method: str,
        path: str,
        *,
        response_type: type[T],
        query: dict[str, str] | None = None,
        payload: GitHubAuthenticatedReaderSync
        | InvocationEventBatch
        | OAuthSessionEvent
        | None = None,
        expect_body: bool = True,
    ) -> T:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.service_token}",
            "User-Agent": "mcp-bridge",
        }
        if payload is not None:
            body = payload.model_dump_json().encode("utf-8")
            headers["Content-Type"] = "application/json"
        normalized_method = method.upper()
        try:
            response = self._transport.request(
                normalized_method,
                self._target(path, query),
                body=body,
                headers=headers,
                reconnect_retries=1 if normalized_method in {"GET", "HEAD"} else 0,
            )
        except HttpTransportError as exc:
            raise AdminApiClientError(f"admin-api transport error: {exc}") from exc
        if response.status >= 400:
            detail = response.body[:2048].decode("utf-8", "replace")
            raise AdminApiClientError(f"admin-api HTTP {response.status}: {detail}")
        if not expect_body or not response.body:
            return response_type.model_validate({})
        return response_type.model_validate_json(response.body)

    def list_accounts(
        self,
        *,
        provider: str | None = None,
    ) -> AccountList:
        provider_key = (provider or "").strip().casefold()
        cache_key = self.cache_keys.account_list(provider_key)
        cached = self.cache.get_model(cache_key, AccountList)
        if cached is not None:
            return cached

        query: dict[str, str] = {}
        if provider:
            query["provider"] = provider
        data = self._request("GET", "/internal/accounts", query=query, response_type=AccountList)
        result = data
        self.cache.set_model(
            cache_key,
            result,
            ttl_seconds=self.cache_settings.account_list_ttl_seconds,
        )
        return result

    def resolve_account(
        self,
        selector: str,
        *,
        provider: str,
    ) -> ResolvedAccount:
        value = selector.strip()
        if not value:
            raise ValueError("account_id is required")
        provider_key = provider.strip().casefold()
        cache_key = self.cache_keys.account(provider_key, value)
        cached = self.cache.get_model(cache_key, ResolvedAccount)
        if cached is not None:
            return cached

        query = {"provider": provider}
        path = "/internal/accounts/" + urllib.parse.quote(value, safe="") + "/resolve"
        try:
            data = self._request("GET", path, query=query, response_type=ResolvedAccount)
        except AdminApiClientError as exc:
            if "admin-api HTTP 404:" not in str(exc):
                raise
            accounts = self.list_accounts(provider=provider)
            aliases = sorted(account.alias for account in accounts.accounts if account.alias)
            hint = f"; use stable account alias instead: {', '.join(aliases)}" if aliases else ""
            raise AdminApiClientError(
                f"{provider} account selector not found: {value}{hint}"
            ) from exc

        account = data
        selectors = {value.casefold(), account.id.casefold(), account.alias.casefold()}
        for resolved_selector in selectors:
            self.cache.set_model(
                self.cache_keys.account(provider_key, resolved_selector),
                account,
                ttl_seconds=self.cache_settings.account_ttl_seconds,
            )
        return account

    def sync_github_authenticated_reader(
        self, token: str, *, login: str
    ) -> AuthenticatedReaderView:
        payload = GitHubAuthenticatedReaderSync(token=token, login=login)
        result = self._request(
            "PUT",
            "/internal/accounts/github/authenticated-reader",
            payload=payload,
            response_type=AuthenticatedReaderView,
        )
        self.cache.delete(
            self.cache_keys.account_list("github"),
            self.cache_keys.account("github", "authenticated"),
        )
        return result

    def record_invocation(self, event: InvocationEvent) -> None:
        self.record_invocations([event])

    def record_invocations(self, events: list[InvocationEvent]) -> None:
        if not events:
            return
        batch = InvocationEventBatch(events=events)
        trace.get_current_span().set_attribute("audit.batch.size", len(events))
        self._request(
            "POST",
            "/internal/events/batch",
            payload=batch,
            expect_body=False,
            response_type=AdminApiAcknowledgement,
        )

    def _runtime_policy[T: BaseModel](self, path: str, cache_key: str, response_type: type[T]) -> T:
        cached = self.cache.get_model(cache_key, response_type)
        if cached is not None:
            return cached
        result = self._request("GET", path, response_type=response_type)
        self.cache.set_model(cache_key, result, ttl_seconds=self.cache_settings.policy_ttl_seconds)
        return result

    def terminal_runtime_policy(self) -> TerminalRuntimePolicy:
        return self._runtime_policy(
            "/internal/runtime-settings/terminal",
            self.cache_keys.terminal_policy(),
            TerminalRuntimePolicy,
        )

    def mcp_runtime_policy(self) -> McpRuntimePolicy:
        return self._runtime_policy(
            "/internal/runtime-settings/mcp", self.cache_keys.mcp_policy(), McpRuntimePolicy
        )

    def github_runtime_policy(self) -> GitHubRuntimePolicy:
        return self._runtime_policy(
            "/internal/runtime-settings/github",
            self.cache_keys.github_policy(),
            GitHubRuntimePolicy,
        )

    def gitlab_runtime_policy(self) -> GitLabRuntimePolicy:
        return self._runtime_policy(
            "/internal/runtime-settings/gitlab",
            self.cache_keys.gitlab_policy(),
            GitLabRuntimePolicy,
        )

    def browser_runtime_policy(self) -> BrowserRuntimePolicy:
        return self._runtime_policy(
            "/internal/runtime-settings/browser",
            self.cache_keys.browser_policy(),
            BrowserRuntimePolicy,
        )

    def browser_launcher_policy(self) -> BrowserLauncherPolicy:
        return self._request(
            "GET",
            "/internal/runtime-settings/browser-launcher",
            response_type=BrowserLauncherPolicy,
        )

    def record_oauth_session(self, event: OAuthSessionEvent) -> None:
        self._request(
            "POST",
            "/internal/oauth-sessions/events",
            payload=event,
            expect_body=False,
            response_type=AdminApiAcknowledgement,
        )
